"""Knowledge-base search (practice standards and design rules) and species lookup."""

from __future__ import annotations

from fastapi import APIRouter, Query

from tr_kb import store

from .auth import CurrentUser
from .db import fetch_all, get_engine

router = APIRouter()


@router.get("/api/knowledge/search")
def knowledge_search(user: CurrentUser, q: str = Query(..., min_length=2, max_length=300),
                     source: str | None = Query(None, pattern="^(nrcs_cps|rules|references|interventions)$"), limit: int = Query(6, ge=1, le=20)):
    with get_engine().connect() as conn:
        hits = store.search(conn, q, limit=limit, source=source)
    return [{**h, "score": round(float(h["score"]), 4)} for h in hits]


@router.get("/api/knowledge/rules")
def knowledge_rules(user: CurrentUser):
    return fetch_all(
        """SELECT d.code AS id, d.title, d.version, d.meta->>'status' AS status, d.meta->'applies_to' AS applies_to,
                  d.meta->'parameters' AS parameters, d.meta->'sources' AS sources,
                  (SELECT string_agg(c.body, E'\\n' ORDER BY c.ordinal) FROM kb_chunks c WHERE c.document_id = d.id) AS body
           FROM kb_documents d WHERE d.source = 'rules' ORDER BY d.title"""
    )


@router.get("/api/knowledge/stats")
def knowledge_stats(user: CurrentUser):
    docs = fetch_all("SELECT source, count(*) AS documents FROM kb_documents GROUP BY source ORDER BY source")
    chunks = fetch_all(
        """SELECT d.source, count(*) AS chunks, count(c.embedding) AS embedded
           FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id GROUP BY d.source"""
    )
    species = fetch_all("SELECT count(*) AS species FROM species")[0]["species"]
    return {"documents": docs, "chunks": chunks, "species": species}


@router.get("/api/species")
def species_search(user: CurrentUser, q: str | None = Query(None, max_length=100), growth_habit: str | None = None,
                   nitrogen_fixing: bool = False, drought_tolerance: str | None = None, shade_tolerance: str | None = None,
                   min_temp_f_at_most: float | None = None, limit: int = Query(20, ge=1, le=100)):
    with get_engine().connect() as conn:
        return store.find_species(conn, q, growth_habit=growth_habit, nitrogen_fixing=nitrogen_fixing,
                                  drought_tolerance=drought_tolerance, shade_tolerance=shade_tolerance,
                                  min_temp_f_at_most=min_temp_f_at_most, limit=limit)
