-- Users (from Clerk) and project ownership.
CREATE TABLE IF NOT EXISTS users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_user_id text NOT NULL UNIQUE,
    email         text,
    name          text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id uuid REFERENCES users (id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS projects_owner_idx ON projects (owner_id, created_at DESC);
