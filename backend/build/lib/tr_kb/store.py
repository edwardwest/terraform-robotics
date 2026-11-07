"""Write documents, chunks and species to PostgreSQL, and search them.

Search is hybrid: PostgreSQL full-text rank plus pgvector cosine similarity when embeddings exist, merged by
reciprocal rank so either signal alone still works.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from .chunking import chunk
from .embeddings import get_embedder, to_pgvector


def upsert_document(conn, *, source: str, doc_key: str, title: str, body: str, license: str, commercial_ok: bool,
                    code: str | None = None, url: str | None = None, version: str | None = None,
                    meta: dict | None = None, embed: bool = True) -> int:
    """Insert or replace a document and its chunks. Returns the number of chunks written."""
    doc_id = conn.execute(
        text("""INSERT INTO kb_documents (source, doc_key, title, code, url, license, commercial_ok, version, meta)
                VALUES (:source, :key, :title, :code, :url, :license, :ok, :version, CAST(:meta AS jsonb))
                ON CONFLICT (doc_key) DO UPDATE SET title = EXCLUDED.title, code = EXCLUDED.code, url = EXCLUDED.url,
                    license = EXCLUDED.license, commercial_ok = EXCLUDED.commercial_ok, version = EXCLUDED.version,
                    meta = EXCLUDED.meta, fetched_at = now()
                RETURNING id"""),
        {"source": source, "key": doc_key, "title": title, "code": code, "url": url, "license": license,
         "ok": commercial_ok, "version": version, "meta": json.dumps(meta or {})},
    ).scalar_one()
    conn.execute(text("DELETE FROM kb_chunks WHERE document_id = :id"), {"id": doc_id})
    pieces = chunk(body)
    if not pieces:
        return 0
    embedder = get_embedder() if embed else None
    vectors = embedder.embed([f"{title}. {h or ''}. {b}" for h, b in pieces], "document") if embedder else [None] * len(pieces)
    conn.execute(
        text("""INSERT INTO kb_chunks (document_id, ordinal, heading, body, embedding)
                VALUES (:doc, :ord, :head, :body, CAST(:emb AS vector))"""),
        [{"doc": doc_id, "ord": i, "head": h, "body": b, "emb": to_pgvector(v) if v else None}
         for i, ((h, b), v) in enumerate(zip(pieces, vectors))],
    )
    return len(pieces)


def upsert_species(conn, rows: list[dict], source: str, license: str) -> int:
    if not rows:
        return 0
    conn.execute(
        text("""INSERT INTO species (symbol, scientific_name, common_name, family, traits, source, license)
                VALUES (:symbol, :scientific_name, :common_name, :family, CAST(:traits AS jsonb), :source, :license)
                ON CONFLICT (symbol) DO UPDATE SET scientific_name = EXCLUDED.scientific_name,
                    common_name = COALESCE(EXCLUDED.common_name, species.common_name),
                    family = COALESCE(EXCLUDED.family, species.family),
                    traits = species.traits || EXCLUDED.traits, source = EXCLUDED.source, license = EXCLUDED.license,
                    updated_at = now()"""),
        [{**r, "traits": json.dumps(r.get("traits") or {}), "source": source, "license": license} for r in rows],
    )
    return len(rows)


SEARCH_SQL = """
WITH kw AS (
    SELECT c.id, ts_rank_cd(c.tsv, q, 1) AS score, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q, 1) DESC) AS r
    FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id, to_tsquery('english', :qor) q
    WHERE CAST(:has_words AS boolean) AND c.tsv @@ q AND (d.commercial_ok OR NOT CAST(:commercial_only AS boolean)) {source_filter}
    ORDER BY score DESC LIMIT 40
), vec AS (
    SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> CAST(:emb AS vector)) AS r
    FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id
    WHERE CAST(:emb AS text) IS NOT NULL AND c.embedding IS NOT NULL AND (d.commercial_ok OR NOT CAST(:commercial_only AS boolean)) {source_filter}
    ORDER BY c.embedding <=> CAST(:emb AS vector) LIMIT 40
), fused AS (
    SELECT id, sum(1.0 / (60 + r)) AS score FROM (SELECT id, r FROM kw UNION ALL SELECT id, r FROM vec) u GROUP BY id
)
SELECT c.id::text AS chunk_id, d.title, d.code, d.url, d.source, d.license, d.version, c.heading, c.body, f.score,
       coalesce((d.meta->>'link_only')::boolean, false) AS link_only, d.meta->>'work_license' AS work_license
FROM fused f JOIN kb_chunks c ON c.id = f.id JOIN kb_documents d ON d.id = c.document_id
ORDER BY f.score DESC LIMIT :limit
"""


def search(conn, q: str, limit: int = 6, source: str | None = None, commercial_only: bool = True) -> list[dict]:
    embedder = get_embedder()
    emb = None
    if embedder is not None:
        try:
            emb = to_pgvector(embedder.embed([q], "query")[0])
        except Exception:  # keyword search still works if the embedding service is unavailable
            emb = None
    sql = SEARCH_SQL.format(source_filter="AND d.source = :source" if source else "")
    import re

    words = [w for w in re.findall(r"[A-Za-z0-9]+", q.lower()) if len(w) > 1][:30]
    params = {"qor": " | ".join(words) if words else "x", "has_words": bool(words), "emb": emb, "limit": limit,
              "commercial_only": commercial_only}
    if source:
        params["source"] = source
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


SPECIES_FILTERS = {
    "growth_habit": "traits->>'growth_habit' ILIKE :growth_habit",
    "nitrogen_fixation": "coalesce(traits->>'nitrogen_fixation', '') NOT IN ('', 'None', 'none', 'No')",
    "drought_tolerance": "traits->>'drought_tolerance' ILIKE :drought_tolerance",
    "shade_tolerance": "traits->>'shade_tolerance' ILIKE :shade_tolerance",
    "native": "traits::text ILIKE '%native%'",
}


def find_species(conn, q: str | None = None, *, growth_habit: str | None = None, nitrogen_fixing: bool = False,
                 drought_tolerance: str | None = None, shade_tolerance: str | None = None,
                 min_temp_f_at_most: float | None = None, limit: int = 20) -> list[dict]:
    where, params = [], {"limit": limit}
    if q:
        where.append("(to_tsvector('simple', scientific_name || ' ' || coalesce(common_name, '')) @@ plainto_tsquery('simple', :q)"
                     " OR scientific_name ILIKE :qlike OR common_name ILIKE :qlike)")
        params.update(q=q, qlike=f"%{q}%")
    if growth_habit:
        where.append(SPECIES_FILTERS["growth_habit"])
        params["growth_habit"] = f"%{growth_habit}%"
    if nitrogen_fixing:
        where.append(SPECIES_FILTERS["nitrogen_fixation"] + " AND traits ? 'nitrogen_fixation'")
    if drought_tolerance:
        where.append(SPECIES_FILTERS["drought_tolerance"])
        params["drought_tolerance"] = f"%{drought_tolerance}%"
    if shade_tolerance:
        where.append(SPECIES_FILTERS["shade_tolerance"])
        params["shade_tolerance"] = f"%{shade_tolerance}%"
    if min_temp_f_at_most is not None:
        where.append("(traits->>'min_temp_f') ~ '^-?[0-9.]+' AND substring(traits->>'min_temp_f' from '^-?[0-9.]+')::float <= :mint")
        params["mint"] = min_temp_f_at_most
    sql = ("SELECT symbol, scientific_name, common_name, family, traits, source, license FROM species"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY (common_name IS NULL), jsonb_object_keys_count(traits) DESC, scientific_name LIMIT :limit")
    sql = sql.replace("jsonb_object_keys_count(traits)", "(SELECT count(*) FROM jsonb_object_keys(traits))")
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
