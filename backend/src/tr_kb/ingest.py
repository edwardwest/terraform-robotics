"""Knowledge-base ingestion: `tr-worker kb rules|nrcs|plants|all [--limit N]`.

Runs where the internet is reachable (a Cloud Run Job, or Cloud Shell). Each source is idempotent: re-running
replaces documents by key.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from . import nrcs, plants, rules
from .store import upsert_document, upsert_species

log = logging.getLogger("tr_kb")
PLANTS_URL = os.environ.get("PLANTS_DWCA_URL", "https://zenodo.org/records/17903503/files/usda_plant_traits.tar.gz?download=1")


def _engine():
    from tr_api.db import get_engine

    return get_engine()


def ingest_rules() -> int:
    n = 0
    with _engine().begin() as conn:
        for d in rules.rule_documents():
            n += upsert_document(conn, **d)
    log.info("rules: %d chunks", n)
    return n


def ingest_nrcs(limit: int | None = None, pause_s: float = 0.5) -> dict:
    stats = {"practices": 0, "documents": 0, "chunks": 0, "failed": []}
    with httpx.Client(timeout=60, headers={"User-Agent": nrcs.USER_AGENT}) as client:
        practices = nrcs.parse_index(client.get(nrcs.INDEX_URL).text)
        log.info("nrcs: %d practices in the index", len(practices))
        for p in practices[: limit or None]:
            stats["practices"] += 1
            try:
                pdfs = nrcs.parse_practice_pdfs(client.get(p.url).text, p.url)
                for kind in ("standard", "overview"):
                    if kind not in pdfs:
                        continue
                    body = nrcs.pdf_text(nrcs.fetch(client, pdfs[kind]))
                    if len(body.strip()) < 200:
                        continue
                    with _engine().begin() as conn:
                        stats["chunks"] += upsert_document(
                            conn, source="nrcs_cps", doc_key=f"nrcs_cps:{p.code}:{kind}",
                            title=f"NRCS {p.code} {p.name}" + (" (overview)" if kind == "overview" else ""),
                            code=p.code, url=pdfs[kind], body=body, license=nrcs.LICENSE, commercial_ok=True,
                            version=p.version, meta={"unit": p.unit, "kind": kind, "practice_page": p.url},
                        )
                    stats["documents"] += 1
                    time.sleep(pause_s)
            except Exception as e:  # one bad PDF should not stop the crawl
                log.warning("nrcs %s failed: %s", p.code, e)
                stats["failed"].append(p.code)
    log.info("nrcs: %s", stats)
    return stats


def ingest_plants(url: str = PLANTS_URL) -> int:
    with httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": nrcs.USER_AGENT}) as client:
        data = client.get(url).content
    rows = plants.parse_dwca(data)
    with _engine().begin() as conn:
        n = upsert_species(conn, rows, plants.SOURCE, plants.LICENSE)
    log.info("plants: %d species", n)
    return n


def main(args: list[str]) -> int:
    if not args or args[0] not in ("rules", "nrcs", "plants", "all"):
        print("usage: tr-worker kb rules|nrcs|plants|all [--limit N]")
        return 2
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    what = args[0]
    if what in ("rules", "all"):
        ingest_rules()
    if what in ("nrcs", "all"):
        ingest_nrcs(limit)
    if what in ("plants", "all"):
        ingest_plants()
    return 0
