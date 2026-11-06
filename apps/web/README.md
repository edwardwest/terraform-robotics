# Terraform Robotics web app (Stage 1)

Next.js 15 (App Router) + TypeScript + React 19, MapLibre GL for maps, terra-draw for the boundary polygon.
Plain CSS: `src/styles/globals.css` plus CSS Modules, with design tokens generated from
`packages/design-tokens/tokens.json`.

## Run

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000 (runs `tokens` and `assets` first)
```

The API must be running (`cd backend && uvicorn tr_api.main:app --reload`, port 8000).

| Script | What it does |
| --- | --- |
| `npm run dev` | Dev server. Regenerates `src/styles/tokens.css` and copies the MapLibre worker first. |
| `npm run build` / `npm start` | Production build and server. |
| `npm run tokens` | `node ../../packages/design-tokens/build.mjs` → `src/styles/tokens.css`. |
| `npm run assets` | Copies `maplibre-gl-worker.mjs` to `public/vendor/` (MapLibre v6 loads its worker by URL). |
| `npm run typecheck` | `tsc --noEmit`. |
| `npm test` | Unit tests for `src/lib/units.ts` (Node's built-in test runner, Node ≥ 22.18). |

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_URL` | `http://localhost:8000` | Where `/api/*` and `/files/*` are proxied (route handlers in `src/app/api` and `src/app/files`). Read at request time, so set it when the server starts. |
| `NEXT_PUBLIC_SATELLITE_TILES` | empty | Optional XYZ raster template, e.g. `https://tiles.example.com/{z}/{x}/{y}.jpg`. When set, the **Basemap** chip toggles it under the analysis layers. Inlined at build time. |

### Basemap

By default the map style is a black background only, with the parcel boundary and analysis layers on top.
Nothing loads from a third-party tile service and no glyph server is used (keypoint labels are HTML markers).
Set `NEXT_PUBLIC_SATELLITE_TILES` to add imagery; the chip is disabled when it is unset.

3D: **Tilt to 3D** pitches the map. If the terrain summary ever includes `dem_tiles_url` (terrarium-encoded
XYZ tiles, not in the Stage 1 contract), the app also adds a `raster-dem` source for 3D terrain and enables the
Hillshade layer; otherwise Hillshade is shown disabled.

## Routes

| Route | Screen |
| --- | --- |
| `/` | Project list, or the empty state ("Start with the land.") |
| `/projects/new` | Step 1, site setup for a new project (POST `/api/projects`) |
| `/projects/[id]/site` | Step 1 for an existing project (PUT `/boundary` if changed) |
| `/projects/[id]/survey` | Step 2, survey sources and data quality; "Build terrain model" POSTs a terrain job |
| `/projects/[id]/terrain` | Step 3, terrain map, layers, keypoints, section profile; polls the job (`?job=` or sessionStorage) |

## Code map

- `src/lib/api.ts` typed client for `docs/api.md`. Keep in sync with `tr_api/schemas.py`.
- `src/lib/units.ts` metric → feet / acres / miles. The API is metric; convert only here.
- `src/lib/geo.ts` area/perimeter (@turf/area, @turf/length) and GeoJSON boundary parsing.
- `src/lib/maplibre.ts`, `src/lib/useMap.ts` map setup, base style, worker URL.
- `src/components/BoundaryMap.tsx` terra-draw polygon + select (vertex edit) modes.
- `src/components/terrain/layers.ts` monochrome layer styles.

## Design notes

- Strictly monochrome and dark. Colours come only from tokens (`var(--ink-0)`, `var(--fg-3)`, ...); the only
  hard-coded values are white/black alpha line styles on the map, which follow the design spec.
- Cards are flat: `rgba(255,255,255,0.06)` fill, 1px `--border-subtle`, 12px radius; hover and selected use
  `--border-strong`. Pills and buttons are 10px; map panels 24px (left corners only on the site screen, where
  the map bleeds right). No shadows.
- Primary button: white fill, black bold text. Secondary: `--surface-pill`.
- Type comes from the generated `.app-*` classes. Eyebrows are 11px, 0.18em, uppercase, `--fg-label`.
- Contour-arcs motif (`ContourArcs.tsx`) appears only on the empty state and the "Old survey or drawing" card.
- Touch targets are at least 44px; icon buttons have `aria-label`; icons are inline 1.5-stroke SVGs. No emoji.
- Layout is fluid: side panels wrap under the map below 1280px / 860px; no horizontal scroll at 390px.
