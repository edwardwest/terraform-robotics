"""USDA PLANTS species and traits from a Darwin Core Archive (the EOL/Zenodo "USDA plant traits" export).

The archive's meta.xml names its files and columns (as <core>/<extension>, or EOL-style <table> elements), so
the parser follows it rather than assuming file names. Measurements may point at taxa directly (taxonID) or
through an occurrence table (occurrenceID -> taxonID), as the EOL export does.

The EOL export is large (a ~300 MB measurement table), so tables are streamed from the archive rather than
read into memory. Values are mostly ontology IRIs; VALUE_LABELS gives their labels (looked up in EBI OLS),
and min/max/mature statistics become separate keys (ph_min, ph_max, height_ft_mature).

USDA PLANTS is a US government work (public domain).
"""

from __future__ import annotations

import csv
import io
import re
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

LICENSE = "US government work (public domain)"
SOURCE = "USDA PLANTS (via EOL trait export)"

csv.field_size_limit(10**8)

# Ontology value labels (EBI OLS lookups). SNOMED 260413007 is the "None" qualifier.
VALUE_LABELS = {
    "SNOMEDCT/260413007": "None", "C49507": "Medium", "C54722": "Low", "C25227": "High", "C48658": "Indeterminate",
    "C63815": "Irregular", "C94730": "Winter", "C94731": "Spring", "C94732": "Summer", "C94733": "Autumn",
    "FLOPO_0022142": "Herbaceous", "FLOPO_0900033": "Tree", "FLOPO_0900034": "Shrub", "FLOPO_0900035": "Vine",
    "FLOPO_0900036": "Graminoid", "PATO_0000461": "Normal", "PATO_0000911": "Slow", "PATO_0000912": "Rapid",
    "PATO_0000984": "Porous", "PATO_0000320": "Green", "PATO_0001731": "Deciduous", "PATO_0001733": "Evergreen",
    "PATO_0000622": "Erect", "PATO_0002260": "Semi-erect", "PATO_0000631": "Prostrate", "PATO_0000952": "Brown",
    "PATO_0000324": "Yellow", "PATO_0000323": "White", "PATO_0000322": "Red", "PATO_0000951": "Purple",
    "PATO_0000317": "Black", "PATO_0000318": "Blue", "PATO_0000953": "Orange", "PATO_0000700": "Rough",
    "PATO_0000701": "Smooth", "PATO_0001603": "Long", "PATO_0001604": "Short", "PATO_0000394": "Mild",
    "PATO_0000395": "Moderate", "PATO_0000396": "Severe", "PATO_0002397": "Rounded", "PATO_0002021": "Conical",
    "PATO_0001891": "Ovate",
    # tolerance qualifiers; SHADE_LABELS below gives the PLANTS wording for shade
    "PATO_0002393": "Tolerant", "PATO_0002394": "Intolerant",
}
SHADE_LABELS = {"Tolerant": "Tolerant", "Intolerant": "Intolerant", "Normal": "Intermediate"}

# Measurement types (IRI tail or PLANTS "Source term") -> trait key.
TYPE_KEYS = {
    "TO_0002725": "duration", "FLOPO_0900032": "growth_form", "TO_0000207": "height_ft", "TO_0000276": "drought_tolerance",
    "TO_0006001": "salinity_tolerance", "TO_0000624": "allelopathic", "TO_0000326": "foliage_color",
    "TO_0000537": "flower_color", "GO_0009399": "nitrogen_fixation", "SNOMEDCT/260865002": "growth_rate",
    "PATO_0001729": "leaf_retention", "PATO_0000052": "shape", "PATO_0000050": "lifespan",
    "ShadeTolerance": "shade_tolerance", "TemperatureTolerance": "min_temp_f", "FrostFreeDays": "frost_free_days",
    "SoilPH": "ph", "PrecipitationTolerance": "precip_in", "SoilDepth": "root_depth_in", "PlantingDensity": "planting_density_per_acre",
    "NativeRange": "native_range", "IntroducedRange": "introduced_range", "Present": "states",
    "PropagationMethod": "propagation", "SoilRequirements": "soil",
}
# Plain-text measurement names some archives use instead of IRIs.
NAME_KEYS = {
    "growth habit": "growth_habit", "drought tolerance": "drought_tolerance", "nitrogen fixation": "nitrogen_fixation",
    "shade tolerance": "shade_tolerance", "temperature minimum": "min_temp_f", "minimum temperature": "min_temp_f",
    "height mature": "height_ft_mature", "mature height": "height_ft_mature", "growth rate": "growth_rate",
    "ph minimum": "ph_min", "ph maximum": "ph_max", "precipitation minimum": "precip_in_min",
    "precipitation maximum": "precip_in_max", "root depth minimum": "root_depth_in_min",
}
STAT_SUFFIX = {"SIO_001113": "min", "SIO_001114": "max", "SIO_001110": "mature"}
FROM_REMARKS = {"native_range", "introduced_range", "states"}  # the value is an id; the remark names the place
FLAGS = {"propagation", "soil"}  # values like "propagatedByBareRootYes" -> list of the "Yes" flags
KEEP_RANKS = {"species", "subspecies", "variety", "form", ""}


def _tail(iri: str) -> str:
    iri = iri.strip().rstrip("/")
    if "SNOMEDCT/" in iri:
        return "SNOMEDCT/" + iri.rsplit("/", 1)[-1]
    return re.split(r"[/#]", iri)[-1] if "://" in iri else iri


def _snake(s: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "trait"


def _words(s: str) -> str:
    """'yellowGreen' -> 'Yellow green'."""
    w = re.sub(r"([a-z])([A-Z])", r"\1 \2", s).replace("_", " ").strip()
    return w[:1].upper() + w[1:].lower() if w else w


def trait_key(measurement_type: str, remarks: str = "") -> str:
    m = re.search(r"Source term: ([^.]+)", remarks or "")
    if m:
        return _snake(m.group(1))
    t = _tail(measurement_type)
    if t in TYPE_KEYS:
        return TYPE_KEYS[t]
    name = " ".join(re.sub(r"([a-z])([A-Z])", r"\1 \2", t).replace(",", " ").replace("_", " ").lower().split())
    return NAME_KEYS.get(name) or _snake(t)


def trait_value(key: str, value: str, remarks: str = "") -> str | None:
    v = value.strip()
    if not v:
        return None
    if key in FROM_REMARKS:
        place = (remarks or "").strip()
        return place or None
    tail = _tail(v)
    if key in FLAGS:
        if not tail.endswith("Yes"):
            return None
        flag = re.sub(r"^(propagatedBy|propagated)", "", tail[:-3])
        return _words(re.sub(r"Soil$", "", flag)) or None
    label = VALUE_LABELS.get(tail)
    if label is None and "://" in v:
        label = _words(tail)
    label = label or v
    if key == "shade_tolerance":
        label = SHADE_LABELS.get(label, label)
    return label


class _Reader(io.RawIOBase):
    """Make a non-seekable tar member stream acceptable to TextIOWrapper."""

    def __init__(self, f):
        self.f = f

    def readable(self):
        return True

    def readinto(self, b):
        data = self.f.read(len(b))
        b[: len(data)] = data
        return len(data)


class Archive:
    """Stream tables from a .tar.gz or .zip archive (path or bytes)."""

    def __init__(self, src: str | bytes):
        self.src = src

    def _open_src(self):
        return io.BytesIO(self.src) if isinstance(self.src, (bytes, bytearray)) else open(self.src, "rb")

    @contextmanager
    def open(self, name: str) -> Iterator[io.TextIOBase]:
        with self._open_src() as raw:
            if zipfile.is_zipfile(raw):
                raw.seek(0)
                with zipfile.ZipFile(raw) as z:
                    member = next(n for n in z.namelist() if n.split("/")[-1] == name)
                    with z.open(member) as f:
                        yield io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                return
            raw.seek(0)
            with tarfile.open(fileobj=raw, mode="r|*") as t:  # streaming: members are read in archive order
                for m in t:
                    if m.isfile() and m.name.split("/")[-1] == name:
                        yield io.TextIOWrapper(io.BufferedReader(_Reader(t.extractfile(m)), 1 << 20), encoding="utf-8",
                                               errors="replace", newline="")
                        return
            raise KeyError(name)

    def text(self, name: str) -> str:
        with self.open(name) as f:
            return f.read()

    def rows(self, spec: ET.Element, ns: str) -> Iterator[dict[str, str]]:
        name = spec.find(f"{ns}files/{ns}location").text.strip().split("/")[-1]
        delim = (spec.get("fieldsTerminatedBy") or "\\t").encode().decode("unicode_escape")
        skip = int(spec.get("ignoreHeaderLines") or 0)
        cols = {int(f.get("index")): f.get("term").rstrip("/").split("/")[-1]
                for f in spec.findall(f"{ns}field") if f.get("index") is not None}
        for tag in ("id", "coreid"):
            el = spec.find(f"{ns}{tag}")
            if el is not None:
                cols.setdefault(int(el.get("index")), "_id")
        quote = spec.get("fieldsEnclosedBy") or ""
        with self.open(name) as f:
            reader = (csv.reader(f, delimiter=delim, quotechar=quote) if quote
                      else csv.reader(f, delimiter=delim, quoting=csv.QUOTE_NONE))
            for i, r in enumerate(reader):
                if i < skip or not r:
                    continue
                yield {cols[j]: v for j, v in enumerate(r) if j in cols}


def _specs(meta: ET.Element, ns: str) -> dict[str, ET.Element]:
    out = {}
    for spec in [meta.find(f"{ns}core"), *meta.findall(f"{ns}extension"), *meta.findall(f"{ns}table")]:
        if spec is not None:
            out.setdefault(spec.get("rowType", "").rstrip("/").split("/")[-1], spec)
    return out


def parse_dwca(src: str | bytes) -> list[dict]:
    """Species rows: {symbol, scientific_name, common_name, family, traits{...}} from an archive path or bytes."""
    arc = Archive(src)
    meta = ET.fromstring(arc.text("meta.xml"))
    ns = "{http://rs.tdwg.org/dwc/text/}" if meta.tag.startswith("{") else ""
    specs = _specs(meta, ns)
    if "Taxon" not in specs:
        raise ValueError("No taxon table in the archive's meta.xml")

    by_taxon: dict[str, dict] = {}
    for t in arc.rows(specs["Taxon"], ns):
        tid = t.get("taxonID") or t.get("_id")
        status = (t.get("taxonomicStatus") or "").lower()
        if not tid or not t.get("scientificName") or (t.get("taxonRank") or "").lower() not in KEEP_RANKS:
            continue
        if status and status not in ("valid", "accepted"):
            continue
        by_taxon[tid] = {
            "symbol": _symbol(t, tid),
            "scientific_name": t["scientificName"].strip(),
            "common_name": (t.get("vernacularName") or "").strip() or None,
            "family": (t.get("family") or "").strip() or None,
            "traits": {},
        }
    if not by_taxon:
        raise ValueError("No taxa found in the archive; check its meta.xml")

    occ_taxon: dict[str, str] = {}
    if "Occurrence" in specs:
        for o in arc.rows(specs["Occurrence"], ns):
            tid = o.get("taxonID")
            if tid in by_taxon:
                occ_taxon[o.get("occurrenceID") or o.get("_id")] = tid

    values: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    numeric: dict[str, dict[str, float]] = defaultdict(dict)
    for m in arc.rows(specs["MeasurementOrFact"], ns) if "MeasurementOrFact" in specs else ():
        tid = m.get("taxonID") or occ_taxon.get(m.get("occurrenceID") or m.get("_id") or "")
        if tid not in by_taxon or not m.get("measurementType"):
            continue
        remarks = m.get("measurementRemarks") or ""
        key = trait_key(m["measurementType"], remarks)
        stat = STAT_SUFFIX.get(_tail(m.get("statisticalMethod") or ""))
        raw = (m.get("measurementValue") or "").strip()
        if stat and re.fullmatch(r"-?\d+(\.\d+)?", raw):
            numeric[tid][f"{key}_{stat}"] = float(raw) if "." in raw else int(raw)
            continue
        val = trait_value(key, raw, remarks)
        if val:
            values[tid][key].add(val)

    for tid, row in by_taxon.items():
        traits: dict = {k: sorted(v)[0] if len(v) == 1 else sorted(v) for k, v in values.get(tid, {}).items()}
        traits.update(numeric.get(tid, {}))
        if "min_temp_f_min" in traits:  # PLANTS "Temperature, Minimum (°F)"
            traits["min_temp_f"] = traits.pop("min_temp_f_min")
        if "growth_habit" not in traits and "growth_form" in traits:
            traits["growth_habit"] = traits["growth_form"]
        row["traits"] = traits

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
