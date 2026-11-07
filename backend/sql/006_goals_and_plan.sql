-- Goals brief and intervention plan: what the person wants from the land, and which catalog interventions
-- (tr_kb/rules/interventions.yaml) they have chosen. Idempotent; apply with infra/gcp/migrate.sh.

CREATE TABLE IF NOT EXISTS project_briefs (
    project_id  uuid PRIMARY KEY REFERENCES projects (id) ON DELETE CASCADE,
    brief       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- goals (ranked), setting, budget, ... (see docs/api.md)
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_plan (
    project_id       uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    intervention_id  text NOT NULL,                    -- catalog id, e.g. 'roof-catchment'
    quantity         double precision,                 -- metric, in the intervention's basis (m², m, m³ or count)
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, intervention_id)
);

-- Planning allowances for interventions the design tools don't compute (USD). Deliberately wide: they cover
-- DIY at the low end and contractor installation at the high end. Replace them with local quotes.
INSERT INTO cost_items (owner_id, region, item, label, unit, rate_low, rate_high, note)
SELECT NULL, 'starter', v.item, v.label, v.unit, v.lo, v.hi, v.note
FROM (VALUES
    ('tank_gal',            'Rainwater tanks, installed',          'gallon',        1.00,    3.50, 'Poly tanks, pad, gutters, first-flush diverter and overflow'),
    ('greywater_each',      'Laundry-to-landscape system',         'system',         300,    2500, 'Diverter valve, tubing and mulch basins; DIY to installed'),
    ('rain_garden_sqft',    'Rain garden',                         'sq ft',            4,      18, 'Excavation, soil mix, plants and inlet'),
    ('pond_each',           'Farm pond (small embankment)',        'pond',          8000,   60000, 'Excavation, keyed embankment and spillway; engineering extra'),
    ('check_dam_each',      'Check dam (rock, hand-built)',        'structure',       50,     400, 'One-rock dam or rundown with local rock'),
    ('sheet_mulch_sqft',    'Sheet mulching',                      'sq ft',          0.3,     1.5, 'Cardboard, compost and wood chips'),
    ('cover_crop_acre',     'Cover crop',                          'acre',            60,     200, 'Seed and drilling or broadcasting'),
    ('compost_acre',        'Compost application',                 'acre',           800,    2500, 'About a quarter inch of compost, delivered and spread'),
    ('compost_each',        'Composting bins or windrow pad',      'system',         150,    1500, 'Bins, or a pad and cover for windrows'),
    ('garden_sqft',         'Kitchen garden beds',                 'sq ft',            3,      15, 'Bed prep, compost, drip irrigation; raised beds cost more'),
    ('food_forest_acre',    'Food forest or orchard guild',        'acre',         10000,   45000, 'Trees, guild plants, irrigation and mulch'),
    ('tree_each',           'Shade tree, planted',                 'tree',           150,     600, 'Container tree, planting, stake and drip'),
    ('windbreak_ft',        'Windbreak planting',                  'linear foot',      3,      10, 'Two to three rows of trees and shrubs with protection and drip'),
    ('hedgerow_ft',         'Native hedgerow',                     'linear foot',      4,      12, 'Native shrubs, weed control and establishment irrigation'),
    ('pollinator_acre',     'Pollinator meadow',                   'acre',           400,    2000, 'Site prep and native seed mix'),
    ('riparian_acre',       'Creek-side planting',                 'acre',          2000,    8000, 'Native plants, protection and establishment care'),
    ('fuel_reduction_acre', 'Fuel reduction (defensible space, fuel break)', 'acre', 800,    4000, 'Hand crew or mastication; steep ground costs more'),
    ('brush_berm_ft',       'Brush berms',                         'linear foot',      1,       4, 'Laying cut brush on contour'),
    ('coop_each',           'Chicken coop and run',                'coop',           800,    4000, 'Predator-proof coop and run or mobile coop'),
    ('grazing_acre',        'Rotational grazing setup',            'acre',            50,     300, 'Portable electric fencing, energizer and water'),
    ('access_road_ft',      'Farm road on contour',                'linear foot',      8,      40, 'Grading, rock base and drainage dips'),
    ('tunnel_sqft',         'High tunnel',                         'sq ft',            4,      12, 'Hoop house kit and installation')
) AS v(item, label, unit, lo, hi, note)
WHERE NOT EXISTS (SELECT 1 FROM cost_items c WHERE c.owner_id IS NULL AND c.region = 'starter' AND c.item = v.item);
