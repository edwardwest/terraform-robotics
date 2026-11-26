-- Master plan site settings, one row per project: permaculture zone radii, wind and fire directions, overlays shown.
-- Idempotent; apply with infra/gcp/migrate.sh.

CREATE TABLE IF NOT EXISTS plan_site (
    project_id  uuid PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    settings    jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
