# API contract

Base URL: `/api` (FastAPI, `backend/src/tr_api`). All geometry is GeoJSON in EPSG:4326. Lengths in metres, areas in square metres, elevations in metres; the web app converts to feet and acres for display.

## Authentication

Every endpoint except `GET /api/health` requires `Authorization: Bearer <Clerk session token>`. The web app's server-side proxy attaches it, so the browser never calls the API directly. Requests without a valid token get `401`. Users see only their own projects; another user's project returns `404`.

`GET /api/me` → `{ "id", "clerk_user_id", "email", "name", "created_at" }` (created on first request; email and name come from custom session-token claims).

## Projects

`POST /api/projects`
```json
{ "name": "Sample farm", "address": "123 Ridge Rd", "boundary": { "type": "Polygon", "coordinates": [[[lng, lat], ...]] } }
```
→ `201` `Project`

`GET /api/projects` → `Project[]` (newest first)

`GET /api/projects/{id}` → `Project`

`PUT /api/projects/{id}/boundary` with `{ "boundary": Polygon, "source": "parcel" | "upload" | "drawn" }` → `Project`

`Project`:
```json
{
  "id": "uuid",
  "name": "Sample farm",
  "address": "123 Ridge Rd",
  "boundary": { "type": "Polygon", "coordinates": [] },
  "boundary_source": "drawn",
  "area_m2": 162000.5,
  "perimeter_m": 1640.2,
  "centroid": [-122.8, 38.4],
  "bbox": [minLng, minLat, maxLng, maxLat],
  "created_at": "2026-11-06T20:00:00Z"
}
```

## Surveys

`GET /api/projects/{id}/surveys` → `Survey[]`

`POST /api/projects/{id}/surveys` (multipart: `kind`, `file`) → `201` `Survey`. `kind` is `lidar` (LAS/LAZ), `dem` (GeoTIFF), `contours` (DXF/GeoJSON with elevation attribute).

`POST /api/projects/{id}/surveys/public-dem` → `201` `Survey` of kind `public_dem` (USGS 3DEP, best available resolution).

`Survey`:
```json
{ "id": "uuid", "project_id": "uuid", "kind": "lidar", "filename": "site.laz", "status": "uploaded", "resolution_m": 0.5, "grade": "design", "created_at": "..." }
```
`status`: `uploaded` | `processing` | `ready` | `failed`. `grade`: `design` (≤ 1 m from LiDAR/survey), `planning` (≤ 10 m), `coarse` (> 10 m), or `null` until processed.

## Terrain

`POST /api/projects/{id}/terrain-jobs` with `{ "contour_interval_m": 0.6 }` → `202` `Job`

`GET /api/jobs/{job_id}` → `Job`:
```json
{ "id": "uuid", "project_id": "uuid", "kind": "terrain", "status": "queued", "step": "Conditioning DEM", "step_index": 2, "step_count": 6, "error": null, "created_at": "...", "finished_at": null }
```
`status`: `queued` | `running` | `succeeded` | `failed`.

`GET /api/projects/{id}/terrain` → `TerrainSummary` (404 until a job has succeeded):
```json
{
  "dem_resolution_m": 1.0,
  "elevation_min_m": 42.1, "elevation_max_m": 118.7,
  "mean_slope_pct": 9.4,
  "outlet": { "type": "Point", "coordinates": [] },
  "outlet_direction": "SW",
  "main_valley_count": 2,
  "keypoint_count": 3,
  "quality": { "design_pct": 82.0, "planning_pct": 15.0, "coarse_pct": 3.0 },
  "layers": ["contours", "flow", "valleys", "ridges", "keypoints"],
  "dem_url": "/files/projects/{id}/terrain/dem.tif"
}
```

`GET /api/projects/{id}/layers/{layer}` → GeoJSON `FeatureCollection`
- `contours`: LineString, `properties.elevation_m`, `properties.index` (true on every 5th)
- `flow`: LineString, `properties.accumulation` (upstream cells), `properties.order`
- `valleys`, `ridges`: LineString
- `keypoints`: Point, `properties.id` ("K1"), `properties.elevation_m`, `properties.confirmed`, `properties.score`

`PATCH /api/projects/{id}/keypoints/{kp_id}` with `{ "confirmed": true }` → the keypoint Feature

`GET /api/projects/{id}/profile?coords=lng,lat;lng,lat&samples=200` → `{ "distance_m": [], "elevation_m": [] }` (elevation profile along a line)

## Errors
`{ "detail": "message" }` with 4xx/5xx status.

## Map tiles

`TerrainSummary` also carries `dem_tiles_url` and `slope_tiles_url` (XYZ templates) and `dem_bounds` ([west, south, east, north]).

`GET /api/projects/{id}/tiles/dem/{z}/{x}/{y}.png`: Terrarium-encoded elevation (elevation = R×256 + G + B/256 − 32768) for MapLibre `raster-dem` (hillshade, 3D). Nodata inside a tile is filled from the nearest valid cell; tiles outside the model are empty.

`GET /api/projects/{id}/tiles/slope/{z}/{x}/{y}.png`: slope classes (<5, 5–15, 15–25, 25–35, >35 %) as white with rising opacity.

## Goals, ideas and plan

The goals brief records what the person wants from the land; ideas are catalog interventions (`backend/src/tr_kb/rules/interventions.yaml`) ranked against the brief and the site by `tr_kb.interventions` (plain code, no model); the plan is what they chose.

`GET /api/interventions/catalog` → `{ version, goals[{id,label,hint}], phases[{id,label}], categories[{id,label}], questions{setting,budget,timeline,maintenance,water_sources,constraints: [{id,label}]}, interventions[{id,title,category,phase,summary,maintenance,cost_tier,tool,quantity,nrcs}] }`.

`GET /api/projects/{id}/brief` → `Brief` (all fields null until set).
`PUT /api/projects/{id}/brief` with any subset of `Brief` → merged `Brief`. Fields left out are kept; a field sent as `null` is cleared. Unknown option ids are `422`.

`Brief`:
```json
{
  "goals": ["water_security", "food"],          // ranked, at most 5, from catalog goals
  "setting": "home_acreage", "has_buildings": true,
  "water_sources": ["well"], "annual_rainfall_mm": 760,
  "budget": "5k_25k", "timeline": "1_2_years", "maintenance": "medium",
  "constraints": ["limited_machinery"], "vision": "free text, 1,500 characters at most",
  "updated_at": "..."
}
```

`GET /api/projects/{id}/recommendations` → `{ brief_complete, site{area_m2, has_terrain, mean_slope_pct?, main_valleys?, keypoint_count?, terrain_grade?}, items: Recommendation[] }`, best first. `Recommendation`: `{ id, title, category, phase, summary, fit: "good"|"possible"|"not_suited", score, matched_goals[], reasons[], concerns[], unknowns[], cautions[], maintenance, cost_tier (1-4), nrcs[], rules[], references[{id,title,url,work_license}], tool: "keyline"|"swale"|null, quantity{basis,default}|null, has_allowance, selected }`. `not_suited` means a hard requirement is missing (area, creek, buildings, a valley); `unknowns` (no terrain model yet, an unanswered question) never demote an item.

`GET /api/projects/{id}/plan` → `PlanItem[]` in build order (P.A. Yeomans' scale of permanence: water, access, trees, buildings, fencing, soil). `PlanItem`: `{ intervention_id, title, category, phase, tool, quantity_basis: "area_m2"|"length_m"|"volume_m3"|"count"|null, quantity, notes, cost_item, created_at, placed, measured_quantity }`. `placed` counts proposed master plan features that place the item; `measured_quantity` (metric, in `quantity_basis`, or null) is measured from them and replaces `quantity` in the estimate.
`PUT /api/projects/{id}/plan/{intervention_id}` with `{ quantity?, notes? }` adds or updates an item (quantity in metric, in the item's basis; defaults to the catalog's). Items with a design tool keep no quantity: their cost comes from the design. `DELETE` removes it (`204`).

## Master plan features

What a person places on the map. Types, the fixed categories and their map colors come from the feature library (`backend/src/tr_kb/rules/plan_features.yaml`, `tr_kb.plan_features`).

`GET /api/plan-features/library` → `{ version, categories[{id,label,color}], types[{id,label,category,geometry: "point"|"line"|"polygon",intervention,intervention_title,status,fields[],defaults{}}], roofs[] }`. `fields` lists the settings a type takes beyond label, status and build phase: `species` (species list, `plant_spacing_m`, `row_spacing_m` for areas, `rows` for lines, `height_m`), `building` (`height_m`, `roof`), `capacity` (`capacity_m3`).

`GET /api/projects/{id}/plan-features` → GeoJSON `FeatureCollection` (EPSG:4326) of `PlanFeature`, oldest first.
`POST /api/projects/{id}/plan-features` with `{ type, geometry, label?, status?: "proposed"|"existing", build_phase?: 1|2|3, props? }` → `201` `PlanFeature`. The geometry must be the type's kind (Point, LineString, or a Polygon without holes that doesn't cross itself), at most 5,000 points, on or within 500 m of the property. `props` start from the type's `defaults`; settings the type doesn't take are `422`; species must be USDA PLANTS symbols in the `species` table (names are filled in from it). Label defaults to the type's label, status to the type's. Placing a type that has an `intervention` adds that intervention to the plan if it isn't there.
`PATCH /api/projects/{id}/plan-features/{fid}` with any of `{ type, geometry, label, status, build_phase, props }` → `PlanFeature`. `type` may change only to another type of the same geometry kind; settings the new type doesn't take are dropped and its defaults filled in. `props` replaces the settings as a whole.
`DELETE /api/projects/{id}/plan-features/{fid}` → `204`. The plan keeps the intervention.

`PlanFeature.properties`: `{ id, type, type_label, category, color, label, status, build_phase, props, intervention, area_m2, length_m, perimeter_m, plant_count, created_at, updated_at }`. Areas and lengths are measured on the spheroid; `plant_count` is area ÷ (row × plant spacing), length ÷ plant spacing × rows, or 1 for a single tree, and null when spacing isn't set. Only `proposed` features count toward the plan and estimate.

Exports include master plan features: GeoJSON (`kind: "plan_feature"`), Shapefile (`plan_points`, `plan_lines`, `plan_areas`), KML (a folder per category, styled in its color) and DXF (a `PLAN_<CATEGORY>` layer per category in use, with labels).

### Terrain-aware tools, zones and sectors, checks

`PlanFeatureProps.rows_pattern` (planted areas): `"straight"` (east-west rows, the default) or `"contour"` (rows parallel to the contour through the middle of the area, as in keyline orchards; needs a terrain model, else straight).

`POST /api/projects/{id}/plan-features/contour-line` with `{ start: [lon, lat], end: [lon, lat] }` → `{ geometry: LineString, elevation_m, length_m, end_offset_m }`: the contour through `start`, to the point on it nearest `end`, clipped to the property. Not saved; the app places it as the line feature being drawn. `409` without a terrain model, `422` when the start is outside the property or the ground is too flat.

`GET /api/projects/{id}/plan-features/planting` → GeoJSON `FeatureCollection` of rows (`kind: "row"`, LineString) and plants (`kind: "plant"`, Point) for planted features with a plant spacing, each with `feature_id` and `color`, plus `summary: { feature_id: { plants, rows, pattern: "contour"|"straight"|"line"|"point", note } }`. Plants on the map are thinned past 4,000 per project; counts are complete. The master plan sheet draws its tree symbols from the same layout.

`GET /api/projects/{id}/plan-site` → `{ settings: PlanSiteSettings, center: [lon, lat] | null, center_source: "house"|"property"|null, sun: { summer, winter: { rise, set, noon_altitude } | null }, overlays: FeatureCollection }`. `PUT` with `PlanSiteSettings` → the same. `PlanSiteSettings`: `{ zone_radii_m: [z1, z2, z3, z4] (rising; default 50, 150, 400, 1,000 ft), zone_center: house feature id | null, winds: [{ label, from_deg }] (up to 4), fire_from_deg | null, show_zones, show_sectors, phase_years: [p1, p2, p3] (year each build phase starts, non-decreasing, 0–50; default [0, 2, 4]), flight: [Camera] (up to 12) }`. `Camera`: `{ center: [lon, lat], zoom (1–22), pitch (0–85), bearing, duration_s (1–30, default 6; time to fly here from the previous point) }`. Overlays: zone rings (`kind: "zone"`, `zone` 1–4) around the house (or the middle of the property), and sector wedges (`kind: "sun"|"wind"|"fire"`): the sun's arc from sunrise to sunset at each solstice (computed from the latitude), 45° per wind and 60° for fire, from the direction given. Bearings are degrees clockwise from north.

`GET /api/projects/{id}/plan-scene` → what the 3D view draws (EPSG:4326): `{ phase_years, buildings: FeatureCollection (two parts per building: `part: "walls"` with `height_m` to the eaves, and for pitched roofs `part: "roof"`, a narrower block from `base_m` to the full `height_m`), areas: FeatureCollection (every other drawn area, with its category `color`), trees: [[lon, lat, mature height m, canopy diameter m, years to full size, year planted, kind index]], tree_kinds: [{ type, color }], trees_thinned, terrain }`. Every feature has `year`: −100 for existing features, otherwise its build phase's start year. Tree positions come from the planting layout; natural woodland is scattered at about 0.8 × its canopy width, the same way each time (thinned evenly above 6,000 trees). Mature height: the feature's own `height_m` (unless it is just the library default), else the tallest listed species' USDA PLANTS mature height, else a typical size for the type; years to full size from the slowest listed species' growth rate (Rapid 5, Moderate 10, Slow 18) or the type (`tr_kb.growth`). Estimates, labeled as such in the app.

`GET /api/projects/{id}/plan-checks` → `{ findings: [{ rule, severity: "warning"|"note", title, message, feature_ids[], source, measure }], terrain }`, warnings first. Rules (`tr_kb.plan_checks`): features outside the property; earthworks within 3 m of the property line; animal enclosures within 100 ft of a well (DWR Bulletins 74-81/74-90); manure or compost uphill of a pond, creek, rain garden or well (terrain), or merely close (no terrain); ponds on ground averaging over 15% slope; roads over 16% grade (14 CCR 1273.03) and paths over 20%; plants within 5 ft of a building and woodland within 30 ft of the house (CAL FIRE zones 0 and 1); no defensible space drawn around a house; kitchen gardens and compost over 200 ft from the house or garden; windbreaks within 45° of a set wind. `measure` holds metric values (`distance_m`, `drop_m`, `grade_pct`, `slope_pct`, `angle_deg`). Guidance, not approvals.

## Master plan sheet

An illustrated, print-ready plan of the master plan features (`tr_api.master_sheet`, one SVG renderer for both the preview and the PDF).

`GET /api/projects/{id}/plan-sheet` → `PlanSheetSettings` (defaults when none are saved).
`PUT /api/projects/{id}/plan-sheet` with the whole `PlanSheetSettings` → the saved settings. `PlanSheetSettings`: `{ size: "11x17"|"24x36", title, subtitle (null: the project address), prepared_by, notes, base: "aerial"|"terrain"|"plain", contours, labels: "callouts"|"on_features"|"off", phases: 0–3 (0 all; n phases 1 to n), show_existing, hidden_categories[], hidden_labels[], label_positions: { LABEL TEXT: [x, y] }, schedule }`. Label keys are the label text in upper case, as drawn; features with the same label share one callout. Positions are fractions of the sheet's width and height (the label's left edge and first baseline). Unknown fields, categories or positions outside 0–1 are `422`.
`GET /api/projects/{id}/plan-sheet/svg` → the sheet as `image/svg+xml` from the saved settings (base image at ~110 dpi). Labels are `<g class="lbl" data-key data-x data-y>`. `X-Sheet-Base` says which base was drawn: `aerial` (USGS National Map imagery, faded), `terrain` (hillshade from the DEM: asked for, or the fallback when the imagery can't be reached), or `plain`.
`GET /api/projects/{id}/export/master-plan.pdf` → the same sheet as a PDF (base image at ~200 dpi; `?inline=true` to show rather than download).

The map is drawn north-up in the site's UTM zone at the next standard scale (1 in = N ft) that fits the property and every feature shown. Planted features draw tree symbols at their spacing (capped per feature and per sheet; the schedule's counts are the real ones).

## Design (Stage 2)

Lines are computed by `tr_geo.design` from the terrain model. Designs on planning-grade terrain need `allow_planning: true` and are marked `draft`; coarse terrain is refused (`409`).

`POST /api/projects/{id}/design/keylines`
```json
{ "keypoint_id": "K1", "grade": 0.00333, "spacing_m": 5, "extent": "site" | "valley", "pattern": "parallel" | "graded" | "none", "max_lines": 300, "allow_planning": false }
```
→ `{ group_id, keyline: Feature, rip_count, rip_length_m, area_treated_m2, terrain_grade, notes[] }`. Regenerating for the same keypoint replaces its pattern. The keyline falls at `grade` from the keypoint toward the ridges on both sides; arms stop at ridges, other valleys or the boundary. `parallel` offsets the keyline (Yeomans pattern); `graded` traces each line at `grade` from seeds along the keypoint's valley. `extent: valley` keeps parallel lines between the ridges of that valley.

`POST /api/projects/{id}/design/swales` with `{ "start": [lng, lat], "end": [lng, lat], "width_m": 1.8, "depth_m": 0.45, "berm": true, "allow_planning": false }` → Feature. The swale is the contour through `start`, ending at the point nearest `end`.

`GET /api/projects/{id}/design` → FeatureCollection of LineStrings. Properties: `id, kind (keyline|rip|swale), label, group_id, length_m, draft, notes[]`, plus per kind: rip `pass, position, fall_to_ridges_min, steepest_grade, z_start_m, z_end_m`; swale `elevation_m, width_m, depth_m, cross_section_m2, cut_volume_m3, storage_gal, catchment_m2, terrain_slope_mean_pct, terrain_slope_max_pct`.

`DELETE /api/projects/{id}/design/elements/{element_id}` → `204` (deleting a keyline removes its rip pattern).

`GET /api/projects/{id}/design/elements/{element_id}/profile` → `Profile`.

## Estimate (W6)

`GET /api/projects/{id}/estimate?contingency_pct=15` → `{ lines[{item,label,quantity,unit,rate_low,rate_high,total_low,total_high,basis,group}], build_low/high, design_fee_low/high, contingency_pct, contingency_low/high, total_low/high, quantities{}, draft, note }`. `group` is `design` (quantities from the design geometry) or `plan` (a planning allowance: plan quantity converted to the cost unit × rate). Rates come from the cost library. The per-acre design fee applies only when there are `design` lines.

`GET /api/cost-items` → the user's effective unit costs (starter rows merged with their own). `PUT /api/cost-items/{item}` with `{ rate_low, rate_high }` saves the user's own rate; `DELETE` resets it.

`GET /api/projects/{id}/estimate.xlsx` → spreadsheet with live formulas.

## Exports (W7)

All return a file download: `GET /api/projects/{id}/export/geojson`, `/export/shapefile` (zip: design_lines, boundary, keypoints; WGS84), `/export/kml`, `/export/dxf` (UTM metres; layers BOUNDARY, KEYLINE, RIP, SWALE, BERM, CONTOUR, CONTOUR_INDEX, KEYPOINT), `/export/guidance?format=geojson|shapefile` (rip passes ordered top to bottom, alternating direction), `/export/plan.pdf?contingency_pct=15` (11×17 plan set).

## Address and parcels

`GET /api/geocode?q=...` → `[{label, lng, lat, source}]` (US Census geocoder, county address records, then OpenStreetMap Nominatim).

`GET /api/parcels/at?lng=&lat=` → `{ apn, address, acres, boundary: Polygon, source }` from a county parcel service (`404` where none covers the point). `GET /api/parcels/coverage` lists the counties.

## Knowledge base

`GET /api/knowledge/search?q=&source=nrcs_cps|rules|interventions|references&limit=6` → passages `[{chunk_id, title, code, url, source, license, heading, body, score, link_only, work_license}]`. `references` is a further-reading catalog (OSU open textbooks, OAEC, PINA, Millison videos, standard books): our own descriptions, stored link-only because the works are non-commercial or all rights reserved; `work_license` gives the linked work's terms. Content is tagged with the PINA core-curriculum topics (`tr_kb/rules/topics.yaml`) in `meta.topics`. Hybrid ranking: full-text (any word) plus pgvector similarity (Vertex `text-embedding-005`), fused by reciprocal rank. Embeddings live in pgvector in Cloud SQL with an HNSW cosine index (`sql/005_kb_vector_index.sql`). Only commercially usable sources are stored (NRCS standards and USDA PLANTS are US government works; design rules are in-house).

`GET /api/knowledge/rules` → the design rules library (id, title, status, applies_to, parameters, sources, body).

`GET /api/knowledge/stats` → document, chunk and species counts.

`GET /api/species?q=&growth_habit=&nitrogen_fixing=&drought_tolerance=&shade_tolerance=&min_temp_f_at_most=&limit=` → USDA PLANTS species with traits.

Ingestion: `tr-worker kb rules|nrcs|plants|all [--limit N] [--state CA]`. Rules and plants run as the `kb-ingest` Cloud Run Job (`infra/gcp/kb.sh`). NRCS practice standards come from eFOTG (the state's adopted standards, default CA); eFOTG refuses Cloud Run's network and nrcs.usda.gov refuses Google Cloud entirely, so run that source from Cloud Shell with `infra/gcp/kb-local.sh PROJECT us-west1 nrcs`. Plants come from the EOL export of USDA PLANTS on Zenodo (about 31,700 taxa; about 2,000 with full PLANTS characteristics).

## Design assistant (W9)

`POST /api/projects/{id}/assistant` with `{ "messages": [{ "role": "user"|"assistant", "content": "..." }], "allow_planning": false, "step": "site"|"goals"|"survey"|"terrain"|"ideas"|"design"|"estimate", "page_context": {} }` → `{ reply, model, tool_log[], proposals[], citations[], brief_suggestion }`. `brief_suggestion` is a partial `Brief` (or null) from the assistant's `suggest_brief` tool; nothing is saved until the person applies it with `PUT /brief`. `step` defaults to `design`; `page_context` is a small object (at most 4,000 characters as JSON) describing what is on screen. Claude (Vertex AI) coaches from the in-house app guide (`backend/src/tr_kb/guide/`, one page per step) and calls tools. The step decides the tools, enforced server-side: every step has `get_site_summary` (works before a terrain model exists; includes the brief and plan) and `search_knowledge`; Goals adds `suggest_brief` and `recommend_interventions`; Ideas adds `recommend_interventions`, `suggest_brief` and `find_species`; Design and Estimate add `recommend_interventions`, `find_species` and `get_estimate`; only Design has `propose_keyline_pattern` and `propose_swale` (placed relative to a keypoint, never by coordinates). Design requests on the Design step route to `ASSISTANT_DESIGN_MODEL` (default `claude-opus-5-5`), everything else to `ASSISTANT_MODEL` (default `claude-sonnet-5-5`). Each question is logged as a structured `assistant_question` line (step, coarse tag, first 300 characters) for spotting screens that need work.

`GET /api/projects/{id}/assistant/proposals?status=draft` → `Proposal[]` (`{id, kind, params, preview: FeatureCollection, summary, status, created_at}`).

`POST /api/projects/{id}/assistant/proposals/{pid}/accept` recomputes the proposal from its parameters and saves it to the design; `/discard` marks it discarded. Nothing the assistant proposes enters the design until accepted.
