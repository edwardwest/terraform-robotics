"""Split practice documents into searchable chunks that keep their section heading."""

from __future__ import annotations

import re

# Section headings used across NRCS conservation practice standards.
NRCS_HEADINGS = [
    "DEFINITION", "PURPOSE", "PURPOSES", "CONDITIONS WHERE PRACTICE APPLIES", "CRITERIA", "CONSIDERATIONS",
    "PLANS AND SPECIFICATIONS", "OPERATION AND MAINTENANCE", "REFERENCES", "GENERAL CRITERIA APPLICABLE TO ALL PURPOSES",
]
_HEADING_RE = re.compile(r"^\s*(" + "|".join(re.escape(h) for h in NRCS_HEADINGS) + r")\s*$", re.M)


def clean(text: str) -> str:
    text = text.replace("­", "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)  # hyphenated line breaks
    # drop running headers/footers that NRCS repeats on every page
    text = re.sub(r"(?im)^\s*(NRCS, NHCP|Conservation Practice Standard|page \d+ of \d+|\d+ of \d+)\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sections(text: str) -> list[tuple[str | None, str]]:
    """(heading, body) pairs in document order; text before the first heading has heading None."""
    out, last, head = [], 0, None
    for m in _HEADING_RE.finditer(text):
        body = text[last : m.start()].strip()
        if body:
            out.append((head, body))
        head, last = m.group(1).title(), m.end()
    tail = text[last:].strip()
    if tail:
        out.append((head, tail))
    return out


def chunk(text: str, max_chars: int = 1400, overlap: int = 150) -> list[tuple[str | None, str]]:
    """Chunks no longer than `max_chars`, split on paragraph then sentence boundaries, tagged with their section."""
    out: list[tuple[str | None, str]] = []
    for head, body in sections(clean(text)):
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        buf = ""
        for p in paras:
            pieces = [p] if len(p) <= max_chars else re.split(r"(?<=[.;:])\s+", p)
            for piece in pieces:
                if len(buf) + len(piece) + 1 > max_chars and buf:
                    out.append((head, buf.strip()))
                    buf = buf[-overlap:] + " " if overlap else ""
                buf += piece + "\n"
        if buf.strip():
            out.append((head, buf.strip()))
    return out
