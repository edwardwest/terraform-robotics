-- Terraform Robotics schema, Stage 1. PostgreSQL 16 + PostGIS 3 (Cloud SQL supports both).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS projects (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    address         text,
    boundary        geometry(Polygon, 4326),
    boundary_source text CHECK (boundary_source IN ('parcel', 'upload', 'drawn')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS surveys (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind         text NOT NULL CHECK (kind IN ('lidar', 'dem', 'contours', 'public_dem')),
    filename     text,
    storage_path text,
    status       text NOT NULL DEFAULT 'uploaded' CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
    resolution_m double precision,
    grade        text CHECK (grade IN ('design', 'planning', 'coarse')),
    error        text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS surveys_project_idx ON surveys (project_id);

CREATE TABLE IF NOT EXISTS jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('terrain')),
    status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    step        text,
    step_index  int NOT NULL DEFAULT 0,
    step_count  int NOT NULL DEFAULT 0,
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz,
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS jobs_project_idx ON jobs (project_id, created_at DESC);

-- Latest successful terrain analysis per project.
CREATE TABLE IF NOT EXISTS terrain_results (
    project_id uuid PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    job_id     uuid REFERENCES jobs (id) ON DELETE SET NULL,
    summary    jsonb NOT NULL,
    dem_path   text NOT NULL,
    dem_crs    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS terrain_features (
    id         bigserial PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    layer      text NOT NULL CHECK (layer IN ('contours', 'flow', 'valleys', 'ridges', 'keypoints')),
    geom       geometry(Geometry, 4326) NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS terrain_features_layer_idx ON terrain_features (project_id, layer);
CREATE INDEX IF NOT EXISTS terrain_features_geom_idx ON terrain_features USING gist (geom);
