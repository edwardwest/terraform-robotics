-- Stage 2: design elements (keylines, rip lines, swales) and the unit-cost library for estimates.

CREATE TABLE IF NOT EXISTS design_elements (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('keyline', 'rip', 'swale')),
    group_id    uuid,              -- a keyline and its rip pattern share one group
    label       text,
    geom        geometry(LineString, 4326) NOT NULL,
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,
    properties  jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS design_elements_project ON design_elements (project_id, kind);

-- Unit costs. Rows with owner_id NULL are the starter library; a user's own rows override them by item.
CREATE TABLE IF NOT EXISTS cost_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    uuid REFERENCES users (id) ON DELETE CASCADE,
    region      text NOT NULL DEFAULT 'starter',
    item        text NOT NULL,
    label       text NOT NULL,
    unit        text NOT NULL,
    rate_low    numeric NOT NULL,
    rate_high   numeric NOT NULL,
    note        text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS cost_items_owner_item
    ON cost_items (COALESCE(owner_id, '00000000-0000-0000-0000-000000000000'::uuid), region, item);

-- Starter unit costs (USD). Wide ranges on purpose: replace them with local contractor quotes.
-- Basis notes: published custom rates for subsoiling ran about $17-27/acre (Ohio, 2012) on flat ground;
-- keyline ripping on hillsides with a specialist plow costs more. Machine excavation and shaping on site
-- runs roughly $8-25 per cubic yard (national cost guides). Other items are planning assumptions.
INSERT INTO cost_items (owner_id, region, item, label, unit, rate_low, rate_high, note)
SELECT NULL, 'starter', v.item, v.label, v.unit, v.lo, v.hi, v.note
FROM (VALUES
    ('rip_acre',      'Keyline ripping',               'acre',          40,   120, 'Custom hire, subsoil plow on contour; hillside premium over flat-ground subsoiling rates'),
    ('layout_acre',   'Field layout and staking',       'acre',          10,    30, 'GPS staking of keylines and swale lines'),
    ('swale_yd3',     'Swale excavation',               'cubic yard',     8,    25, 'Excavate and place on the downhill berm; no hauling'),
    ('berm_ft',       'Berm shaping and seeding',       'linear foot',  1.5,     4, 'Compact, shape and seed the swale berm'),
    ('mobilization',  'Equipment mobilization',         'machine',      500,  1500, 'Delivery and pickup per machine type'),
    ('design_acre',   'Design, plan set and machine paths', 'acre',      25,    80, 'Keyline layout, estimate and exports')
) AS v(item, label, unit, lo, hi, note)
WHERE NOT EXISTS (SELECT 1 FROM cost_items c WHERE c.owner_id IS NULL AND c.region = 'starter' AND c.item = v.item);
