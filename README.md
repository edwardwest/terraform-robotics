# Terraform Robotics

Site survey to regenerative design. Terraform Robotics starts from what a person wants from their land, turns ground data (drone LiDAR, public elevation, legacy drawings) into a terrain model, ranks permaculture interventions (water harvesting, earthworks, soil, plants and trees, fire, animals, access) against those goals and the site, and computes keyline patterns and swales where they fit. The keyline designs are built to feed an autonomous solar keyline robot.

This repository holds **Stage 1 (site to terrain)**, **Stage 2 (keyline design, estimate, exports)** and the **goals-first flow** (goals brief, intervention catalog and plan). Live at https://web-131142126911.us-west1.run.app (sign-in required).

![Terrain and water screen: contours, valleys and two keypoints on a test site](docs/screenshots/stage1-terrain.png)

| Step | What the user does | Built by |
| --- | --- | --- |
| 1. Site | Names the project, finds the address and imports the county parcel (Sonoma County), or draws/uploads a boundary | `apps/web`, `tr_api.parcels` |
| 2. Goals | Ranks up to five goals (water, erosion, fire, food, soil, habitat, animals, income, shelter, stormwater) and answers a few questions on land use, water, budget, upkeep and constraints, by form or by interview with the assistant | `tr_api.plan_api`, `tr_api.assistant` |
| 3. Survey | Adds ground data: drone LiDAR (LAS/LAZ), a DEM, contours, or fetches USGS 3DEP | `tr_api`, `tr_worker` |
| 4. Terrain | Builds the terrain model: contours, flow paths, valleys, ridges, keypoint candidates, data-quality grades; hillshade, slope and 3D from elevation tiles | `tr_worker`, `tr_geo`, `tr_api.tiles` |
| 5. Ideas | Browses catalog interventions ranked against the goals and the site (plain code, no model) and adds them to the plan with quantities | `tr_kb.interventions`, `tr_kb/rules/interventions.yaml` |
| 6. Design | Sees the plan in build order (Yeomans' scale of permanence); keylines through keypoints at a set grade, parallel or graded rip patterns, swales on contour, with design checks | `tr_geo.design`, `tr_api.design_api` |
| 7. Estimate and export | Cost estimate from the design, planning allowances for the rest of the plan, and an editable unit-cost library (+ spreadsheet); PDF plan set, GeoJSON/Shapefile/KML, DXF, GPS guidance paths | `tr_api.outputs`, `tr_api.plan_pdf` |

## Layout

```
apps/web/                  Next.js web app (MapLibre)
backend/
  src/tr_geo/              Pure terrain analysis: DEM conditioning, flow, contours, keypoints
  src/tr_api/              FastAPI service over PostGIS
  src/tr_worker/           Terrain job pipeline (Cloud Run Job in production)
  sql/                     Database schema (PostGIS)
  tests/
packages/design-tokens/    Terraform Robotics design tokens (source of truth for app styling)
infra/gcp/                 Google Cloud build and deploy config
docs/                      API contract and architecture notes
```

## Run locally

Requirements: Docker, or Python 3.12+, Node 22, and PostgreSQL 16 with PostGIS 3.

**With Docker:**
```bash
cp .env.example .env
docker compose up --build
```
Web app on http://localhost:3000, API on http://localhost:8000/docs.

**Without Docker:**
```bash
# database
createdb terraform && psql terraform -f backend/sql/001_init.sql

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://localhost/terraform
uvicorn tr_api.main:app --reload

# web (separate shell): add CLERK_SECRET_KEY from the Clerk dashboard to apps/web/.env.local first
cd apps/web && cp .env.example .env.local && npm install && npm run dev
```

Run tests with `cd backend && pytest` (set `TEST_DATABASE_URL` to include the database tests).

## Sign-in

Users sign in with [Clerk](https://clerk.com) (email or Google), in the **Terraform Robotics** app of the Clerk account. The web app protects every page and forwards the session token to the API, which verifies it against Clerk's public keys (`CLERK_JWKS_URL`) and scopes all data to the signed-in user. For backend-only work without Clerk, set `AUTH_DISABLED=true` on the API.

## How terrain jobs run

The API records a job and dispatches it. Locally (`JOB_RUNNER=inline`) the API runs it in a background thread. On Google Cloud (`JOB_RUNNER=cloudrun`) it starts the `terrain-worker` Cloud Run Job with the job ID; the worker reads inputs from Cloud Storage, writes the DEM and layers back, and updates the job row as it goes.

Pipeline: fetch or ingest elevation → resample to a working DEM → condition (breach depressions) → flow direction and accumulation → valleys, ridges and flow paths → contours → keypoint candidates → data-quality grades.

## Design system

The app follows the Terraform Robotics design system (monochrome, warm greys, Helvetica Neue, flat cards, contour-arc motif). Tokens live in `packages/design-tokens/tokens.json`; `npm run tokens` in `apps/web` regenerates the CSS variables.

## Specs

- Product description, technical specification and the keyline robot brief are maintained as docs outside this repo; `docs/` holds the parts code depends on.
