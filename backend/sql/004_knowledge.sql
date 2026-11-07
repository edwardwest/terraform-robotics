-- Knowledge base: practice standards, design rules and species, searchable by keywords and by meaning.
-- Only commercially usable sources are imported (NRCS standards and USDA PLANTS are US government works;
-- the design rules are our own). Non-commercial sources are kept as link-outs, not content.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS kb_documents (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source        text NOT NULL,             -- 'nrcs_cps' | 'rules' | ...
    doc_key       text NOT NULL UNIQUE,      -- e.g. 'nrcs_cps:378:standard', 'rules:keyline-grade'
    title         text NOT NULL,
    code          text,                      -- NRCS practice code, rule id
    url           text,
    license       text NOT NULL,
    commercial_ok boolean NOT NULL,
    version       text,
    meta          jsonb NOT NULL DEFAULT '{}'::jsonb,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id  uuid NOT NULL REFERENCES kb_documents (id) ON DELETE CASCADE,
    ordinal      int NOT NULL,
    heading      text,
    body         text NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(heading, '') || ' ' || body)) STORED,
    embedding    vector(768)                 -- Vertex AI text embeddings; NULL until embedded
);
CREATE INDEX IF NOT EXISTS kb_chunks_tsv ON kb_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS kb_chunks_doc ON kb_chunks (document_id, ordinal);

CREATE TABLE IF NOT EXISTS species (
    symbol           text PRIMARY KEY,       -- USDA PLANTS symbol, e.g. 'QUAG'
    scientific_name  text NOT NULL,
    common_name      text,
    family           text,
    traits           jsonb NOT NULL DEFAULT '{}'::jsonb,
    source           text NOT NULL,
    license          text NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS species_names ON species USING gin (to_tsvector('simple', scientific_name || ' ' || coalesce(common_name, '')));
CREATE INDEX IF NOT EXISTS species_traits ON species USING gin (traits);

-- AI assistant: conversations and the design proposals it makes (drafts until a person accepts them).
CREATE TABLE IF NOT EXISTS assistant_proposals (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('keyline', 'swale')),
    params      jsonb NOT NULL,
    preview     jsonb NOT NULL,              -- GeoJSON FeatureCollection in lon/lat
    summary     jsonb NOT NULL DEFAULT '{}'::jsonb,
    status      text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'accepted', 'discarded')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assistant_proposals_project ON assistant_proposals (project_id, created_at);
