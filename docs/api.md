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
