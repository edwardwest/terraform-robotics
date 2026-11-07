"""NRCS national conservation practice standards: crawl the index, fetch each standard and overview PDF.

The index page lists one link per practice ("Pond (No.) (378) 07/2022"); each practice page links its
"Standard Document" and "Overview" PDFs. NRCS standards are US government works (public domain).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

INDEX_URL = "https://www.nrcs.usda.gov/resources/guides-and-instructions/conservation-practice-standards"
LICENSE = "US government work (public domain)"
USER_AGENT = "TerraformRobotics-KB/0.1 (knowledge base for a land-design app)"

_PRACTICE_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<unit>[A-Za-z. ]+)\)\s*\(?\s*(?P<code>\d{3})\s*\)?\s*\(?(?P<date>\d{1,2}/\d{4})?\)?\s*$")


@dataclass
class Practice:
    code: str
    name: str
    unit: str | None
    version: str | None
    url: str


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((" ".join("".join(self._text).split()), self._href))
            self._href = None


def links(html: str) -> list[tuple[str, str]]:
    p = _Links()
    p.feed(html)
    return p.links


def parse_index(html: str, base: str = INDEX_URL) -> list[Practice]:
    out, seen = [], set()
    for text, href in links(html):
        if "conservation-practice" not in href:
            continue
        m = _PRACTICE_RE.match(text.replace(")(", ") ("))
        if not m or m["code"] in seen:
            continue
        seen.add(m["code"])
        out.append(Practice(m["code"], m["name"].strip(), m["unit"].strip(), m["date"], urljoin(base, href)))
    return out


def parse_practice_pdfs(html: str, base: str) -> dict[str, str]:
    """{'standard': url, 'overview': url} from a practice page."""
    found: dict[str, str] = {}
    for text, href in links(html):
        if ".pdf" not in href.lower():
            continue
        t = text.lower()
        if "standard document" in t or re.search(r"_cps_", href, re.I):
            found.setdefault("standard", urljoin(base, href))
        elif "overview" in t or re.search(r"_po_", href, re.I):
            found.setdefault("overview", urljoin(base, href))
    return found


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def fetch(client, url: str) -> bytes:
    r = client.get(url, follow_redirects=True)
    r.raise_for_status()
    return r.content
