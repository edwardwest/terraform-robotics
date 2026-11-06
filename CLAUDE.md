# Working in this repo

Terraform Robotics: site survey → terrain model → regenerative design. See README.md for layout and docs/api.md for the API contract.

## Rules
- **Models never compute geometry.** Contours, flow, keylines, volumes and costs come from `tr_geo` code. AI features choose parameters and explain results.
- **Units:** the API and database are metric (metres, m², EPSG:4326 for GeoJSON). Convert to feet/acres/miles only in the web app (`apps/web/src/lib/units.ts`).
- **Analysis runs in a projected CRS.** `tr_geo` works on a DEM in a local UTM zone; reproject vectors back to EPSG:4326 at the API boundary.
- `tr_geo` is pure (numpy/shapely/rasterio, no database, no network). Keep it testable with synthetic terrain in `backend/tests`.
- Contract changes: update `docs/api.md`, `tr_api/schemas.py` and `apps/web/src/lib/api.ts` together.
- Styling: only design tokens from `packages/design-tokens/tokens.json` (monochrome; no accent hue). No emoji in UI.
- Hosting target is Google Cloud (Cloud Run, Cloud Run Jobs, Cloud SQL for PostgreSQL + PostGIS, Cloud Storage). Don't add AWS-specific dependencies.

## Commands
- Backend tests: `cd backend && pytest`
- API dev server: `cd backend && uvicorn tr_api.main:app --reload`
- Web dev: `cd apps/web && npm run dev`
- Regenerate tokens CSS: `cd apps/web && npm run tokens`
