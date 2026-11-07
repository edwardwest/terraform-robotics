"""NRCS conservation practice standards from the Field Office Technical Guide (eFOTG).

eFOTG (efotg.sc.egov.usda.gov) is NRCS's public portal for the standards each state has adopted. Its JSON API
lists the practice folders for a state and the documents in each; files are served from /api/CPSFile/{id}.
We use it instead of crawling nrcs.usda.gov, which does not answer requests from cloud networks.

Each practice folder holds a state's documents titled like "311 CA CPS Alley Cropping 2018", where the type
is CPS (the standard), PO (overview), SOW (statement of work), IR (implementation requirements) or OM
(operation and maintenance). We keep the standard and the overview, newest first.

The standards are US government works (public domain).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BASE = "https://efotg.sc.egov.usda.gov"
LICENSE = "US government work (public domain)"
SECTION_TITLE = re.compile(r"^Section 4\b")
PRACTICES_TITLE = re.compile(r"Conservation Practice Standards", re.I)
FOLDER_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<code>\d{3}[A-Z]?)\)\s*$")
DOC_RE = re.compile(r"^\s*(?P<code>\d{3}[A-Z]?)\s+(?P<state>[A-Z]{2})\s+(?P<kind>[A-Z]+)\b\s*(?P<rest>.*?)\s*$")
KINDS = {"CPS": "standard", "PO": "overview"}

# State FIPS codes used by eFOTG, keyed by postal abbreviation.
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "FL": "12",
    "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22",
    "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30", "NE": "31",
    "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40",
    "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50",
    "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}


@dataclass
class PracticeFolder:
    code: str
    name: str
    folder_id: int


@dataclass
class PracticeDoc:
    resource_id: int
    code: str
    kind: str  # standard | overview
    title: str
    date: str | None
    url: str


def practice_folders(menu: dict) -> list[PracticeFolder]:
    """Practice folders under Section 4 > Conservation Practice Standards, from /api/stateFolder/getMenu."""
    section = next((n for n in menu.get("result") or [] if SECTION_TITLE.match(n.get("title", ""))), None)
    if section is None:
        return []
    parent = next((n for n in section.get("children") or [] if PRACTICES_TITLE.search(n.get("title", ""))), None)
    out, seen = [], set()
    for node in (parent or {}).get("children") or []:
        m = FOLDER_RE.match(" ".join(node.get("title", "").split()))
        if not m or m["code"] in seen:
            continue
        seen.add(m["code"])
        out.append(PracticeFolder(m["code"], m["name"].strip(), int(node["itemId"])))
    return out


def practice_docs(listing: dict, code: str) -> dict[str, PracticeDoc]:
    """Newest standard and overview in a folder, from /api/resourceItem/listByFolderAll."""
    best: dict[str, PracticeDoc] = {}
    items = ((listing.get("result") or {}).get("resourceItems")) or []
    for it in items:
        if not it.get("isDocument") or not it.get("documentUrl"):
            continue
        m = DOC_RE.match(it.get("resourceTitle") or "")
        if not m or m["code"] != code or m["kind"] not in KINDS:
            continue
        kind = KINDS[m["kind"]]
        doc = PracticeDoc(int(it["resourceId"]), code, kind, " ".join(it["resourceTitle"].split()),
                          (it.get("resourceRevisionDate") or "")[:10] or None,
                          f"{BASE}/api/CPSFile/{it['documentUrl']}")
        if kind not in best or (doc.date or "") > (best[kind].date or ""):
            best[kind] = doc
    return best


def fips(state: str) -> str:
    s = state.strip().upper()
    if s.isdigit():
        return s.zfill(2)
    if s not in STATE_FIPS:
        raise ValueError(f"Unknown state {state!r}")
    return STATE_FIPS[s]
