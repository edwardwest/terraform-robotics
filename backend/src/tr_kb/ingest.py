"""Knowledge-base ingestion: `tr-worker kb rules|nrcs|plants|all [--limit N]`.

Runs where the internet is reachable (a Cloud Run Job, or Cloud Shell). Each source is idempotent: re-running
replaces documents by key.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from . import efotg, nrcs, plants, rules
from .store import upsert_document, upsert_species

log = logging.getLogger("tr_kb")
NRCS_STATE = os.environ.get("NRCS_STATE", "CA")
PLANTS_URL = os.environ.get("PLANTS_DWCA_URL", "https://zenodo.org/records/17903503/files/usda_plant_traits.tar.gz?download=1")


def _engine():
    from tr_api.db import get_engine

    return get_engine()


def ingest_rules() -> int:
    n = 0
    with _engine().begin() as conn:
        for d in rules.rule_documents() + rules.reference_documents():
            n += upsert_document(conn, **d)
    log.info("rules and references: %d chunks", n)
    return n


def _json(client, url: str, **params) -> dict:
    r = client.get(url, params=params or None)
    r.raise_for_status()
    return r.json()


def ingest_nrcs(limit: int | None = None, state: str = NRCS_STATE, pause_s: float = 0.5) -> dict:
    """Practice standards (and overviews) a state has adopted, from eFOTG."""
    code = efotg.fips(state)
    stats = {"state": state, "practices": 0, "documents": 0, "chunks": 0, "failed": []}
    with httpx.Client(base_url=efotg.BASE, timeout=60, follow_redirects=True,
                      headers={"User-Agent": nrcs.USER_AGENT}) as client:
        folders = efotg.practice_folders(_json(client, f"/api/stateFolder/getMenu/{code}"))
        if not folders:
            raise RuntimeError("No practice folders found in eFOTG Section 4; its layout may have changed")
        log.info("nrcs: %d practices for %s in eFOTG", len(folders), state)
        for f in folders[: limit or None]:
            stats["practices"] += 1
            try:
                docs = {}
                for nrt in ("true", "false"):  # national-template folders need isNRTVersion=true
                    docs = efotg.practice_docs(_json(client, "/api/resourceItem/listByFolderAll", stateCode=code,
                                                     folderId=f.folder_id, isNRTVersion=nrt), f.code)
                    if docs:
                        break
                for kind in ("standard", "overview"):
                    d = docs.get(kind)
                    if d is None:
                        continue
                    body = nrcs.pdf_text(nrcs.fetch(client, d.url))
                    if len(body.strip()) < 200:
                        continue
                    with _engine().begin() as conn:
                        stats["chunks"] += upsert_document(
                            conn, source="nrcs_cps", doc_key=f"nrcs_cps:{f.code}:{kind}",
                            title=f"NRCS {f.code} {f.name} ({state.upper()})" + (" overview" if kind == "overview" else ""),
                            code=f.code, url=d.url, body=body, license=efotg.LICENSE, commercial_ok=True,
                            version=d.date, meta={"kind": kind, "state": state.upper(), "efotg_title": d.title,
                                                  "efotg_folder": f.folder_id},
                        )
                    stats["documents"] += 1
                    time.sleep(pause_s)
            except Exception as e:  # one bad PDF should not stop the crawl
                log.warning("nrcs %s failed: %s", f.code, e)
                stats["failed"].append(f.code)
    log.info("nrcs: %s", stats)
    return stats


def ingest_plants(url: str = PLANTS_URL) -> int:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".archive") as tmp:
        with httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": nrcs.USER_AGENT}) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                for block in resp.iter_bytes(1 << 20):
                    tmp.write(block)
        tmp.flush()
        rows = plants.parse_dwca(tmp.name)
    log.info("plants: %d species parsed", len(rows))
    n = 0
    for i in range(0, len(rows), 2000):
        with _engine().begin() as conn:
            n += upsert_species(conn, rows[i : i + 2000], plants.SOURCE, plants.LICENSE)
    log.info("plants: %d species", n)
    return n


def main(args: list[str]) -> int:
    if not args or args[0] not in ("rules", "nrcs", "plants", "all"):
        print("usage: tr-worker kb rules|nrcs|plants|all [--limit N] [--state CA]")
        return 2
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    state = args[args.index("--state") + 1] if "--state" in args else NRCS_STATE
    what = args[0]
    if what in ("rules", "all"):
        ingest_rules()
    if what in ("nrcs", "all"):
        ingest_nrcs(limit, state)
    if what in ("plants", "all"):
        ingest_plants()
    return 0
