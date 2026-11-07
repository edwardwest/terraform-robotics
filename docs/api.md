# API contract (Stage 1)

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

`GET /api/projects/{id}/estimate?contingency_pct=15` → `{ lines[{item,label,quantity,unit,rate_low,rate_high,total_low,total_high,basis}], build_low/high, design_fee_low/high, contingency_pct, contingency_low/high, total_low/high, quantities{}, draft, note }`. Quantities come from the design; rates from the cost library.

`GET /api/cost-items` → the user's effective unit costs (starter rows merged with their own). `PUT /api/cost-items/{item}` with `{ rate_low, rate_high }` saves the user's own rate; `DELETE` resets it.

`GET /api/projects/{id}/estimate.xlsx` → spreadsheet with live formulas.

## Exports (W7)

All return a file download: `GET /api/projects/{id}/export/geojson`, `/export/shapefile` (zip: design_lines, boundary, keypoints; WGS84), `/export/kml`, `/export/dxf` (UTM metres; layers BOUNDARY, KEYLINE, RIP, SWALE, BERM, CONTOUR, CONTOUR_INDEX, KEYPOINT), `/export/guidance?format=geojson|shapefile` (rip passes ordered top to bottom, alternating direction), `/export/plan.pdf?contingency_pct=15` (11×17 plan set).

## Address and parcels

`GET /api/geocode?q=...` → `[{label, lng, lat, source}]` (US Census geocoder, county address records, then OpenStreetMap Nominatim).

`GET /api/parcels/at?lng=&lat=` → `{ apn, address, acres, boundary: Polygon, source }` from a county parcel service (`404` where none covers the point). `GET /api/parcels/coverage` lists the counties.

## Knowledge base

`GET /api/knowledge/search?q=&source=nrcs_cps|rules&limit=6` → passages `[{chunk_id, title, code, url, source, license, heading, body, score}]`. Hybrid ranking: full-text (any word) plus pgvector similarity (Vertex `text-embedding-005`), fused by reciprocal rank. Only commercially usable sources are stored (NRCS standards and USDA PLANTS are US government works; design rules are in-house).

`GET /api/knowledge/rules` → the design rules library (id, title, status, applies_to, parameters, sources, body).

`GET /api/knowledge/stats` → document, chunk and species counts.

`GET /api/species?q=&growth_habit=&nitrogen_fixing=&drought_tolerance=&shade_tolerance=&min_temp_f_at_most=&limit=` → USDA PLANTS species with traits.

Ingestion runs in the cloud: `tr-worker kb rules|nrcs|plants|all` (see `infra/gcp/kb.sh`).

## Design assistant (W9)

`POST /api/projects/{id}/assistant` with `{ "messages": [{ "role": "user"|"assistant", "content": "..." }], "allow_planning": false }` → `{ reply, model, tool_log[], proposals[], citations[] }`. Claude (Vertex AI) calls tools: `get_site_summary`, `propose_keyline_pattern`, `propose_swale` (placed relative to a keypoint, never by coordinates), `get_estimate`, `search_knowledge`, `find_species`. Design requests route to `ASSISTANT_DESIGN_MODEL` (default `claude-opus-5-5`), others to `ASSISTANT_MODEL` (default `claude-sonnet-5-5`).

`GET /api/projects/{id}/assistant/proposals?status=draft` → `Proposal[]` (`{id, kind, params, preview: FeatureCollection, summary, status, created_at}`).

`POST /api/projects/{id}/assistant/proposals/{pid}/accept` recomputes the proposal from its parameters and saves it to the design; `/discard` marks it discarded. Nothing the assistant proposes enters the design until accepted.
