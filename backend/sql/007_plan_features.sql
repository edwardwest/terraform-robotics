-- Master plan features: what a person places on the map (tr_kb/rules/plan_features.yaml types).
-- Idempotent; apply with infra/gcp/migrate.sh.

CREATE TABLE IF NOT EXISTS plan_features (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    type         text NOT NULL,                     -- library type id, e.g. 'orchard'
    label        text,
    status       text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'existing')),
    build_phase  smallint NOT NULL DEFAULT 1 CHECK (build_phase BETWEEN 1 AND 3),
    geom         geometry(Geometry, 4326) NOT NULL
                 CHECK (GeometryType(geom) IN ('POINT', 'LINESTRING', 'POLYGON')),
    props        jsonb NOT NULL DEFAULT '{}'::jsonb, -- settings: species, spacing, rows, height_m, roof, capacity_m3, notes
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS plan_features_project ON plan_features (project_id, created_at);
