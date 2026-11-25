-- Master plan sheet settings, one row per project (size, title, base map, labels, label positions...).
-- Idempotent; apply with infra/gcp/migrate.sh.

CREATE TABLE IF NOT EXISTS plan_sheets (
    project_id  uuid PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    settings    jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
