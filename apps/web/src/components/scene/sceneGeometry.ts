// Geometry for the 3D view: trees as extruded prisms sized for a given year, and the camera path for fly-throughs.
// Sizes come from the server (tr_kb.growth); this file only turns them into shapes and interpolates the camera.
import type { Feature, FeatureCollection, Polygon } from "geojson";
import type { Camera, PlanScene } from "@/lib/api";

/** Slider value meaning "as the land is today": existing features only. */
export const TODAY = -1;
export const MAX_YEAR = 30;

/** Height and canopy at an age, or null before planting. Must match tr_kb.growth.size_at. */
export function sizeAt(age: number, years: number, height: number, canopy: number): [number, number] | null {
  if (age < 0) return null;
  if (years <= 0) return [height, canopy];
  const f = Math.min(1, 0.15 + 0.85 * (1 - (1 - Math.min(age / years, 1)) ** 1.6));
  return [height * f, canopy * f];
}

/** A steady 0.88–1.12 per tree from its position, so plantings don't look cloned and nothing flickers on redraw.
 * Taller trees get slightly narrower crowns. */
function vary(lon: number, lat: number): number {
  const x = Math.sin(lon * 12.9898e3 + lat * 78.233e3) * 43758.5453;
  return 0.88 + 0.24 * (x - Math.floor(x));
}

function prism(lon: number, lat: number, radiusM: number, sides: number): Polygon {
  const dx = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  const dy = radiusM / 110540;
  const ring: [number, number][] = [];
  for (let i = 0; i <= sides; i++) {
    const a = ((i % sides) / sides) * 2 * Math.PI + Math.PI / sides;
    ring.push([lon + dx * Math.cos(a), lat + dy * Math.sin(a)]);
  }
  return { type: "Polygon", coordinates: [ring] };
}

type Part = { base: number; height: number; color: string };

const TRUNK = "#5c4a3a";
const CONIFER_LIKE = new Set(["windbreak"]);
const SHRUB_LIKE = new Set(["berries", "hedgerow"]);

/** Trunk and canopy prisms for every tree planted by `year`. Broadleaf trees get two canopy tiers; windbreaks get a
 * tapering stack; shrubs a short trunk. Low-poly on purpose: thousands of trees stay smooth on a laptop. */
export function treesAt(scene: PlanScene, year: number): FeatureCollection<Polygon, Part> {
  const out: Feature<Polygon, Part>[] = [];
  const sides = scene.trees.length > 2500 ? 6 : 8;
  for (const [lon, lat, h, c, yrs, planted, k] of scene.trees) {
    const age = planted <= -100 ? 1000 : year - planted;
    const size = year === TODAY && planted > -100 ? null : sizeAt(age, yrs, h, c);
    if (!size) continue;
    const v = vary(lon, lat);
    const ht = size[0] * v;
    const cd = size[1] * (2 - v);
    const kind = scene.tree_kinds[k];
    const color = kind?.color ?? "#5f8a3e";
    const r = Math.max(cd / 2, 0.2);
    const shrub = SHRUB_LIKE.has(kind?.type ?? "");
    const trunkTop = ht * (shrub ? 0.12 : 0.32);
    out.push({ type: "Feature", geometry: prism(lon, lat, Math.max(0.06, cd * 0.05), 5), properties: { base: 0, height: trunkTop, color: TRUNK } });
    if (CONIFER_LIKE.has(kind?.type ?? "")) {
      const tiers: [number, number, number][] = [[0.2, 0.55, 1], [0.55, 0.8, 0.68], [0.8, 1, 0.35]];
      for (const [b, t, s] of tiers) {
        out.push({ type: "Feature", geometry: prism(lon, lat, r * s, sides), properties: { base: ht * b, height: ht * t, color } });
      }
    } else {
      out.push({ type: "Feature", geometry: prism(lon, lat, r, sides), properties: { base: trunkTop, height: ht * 0.82, color } });
      out.push({ type: "Feature", geometry: prism(lon, lat, r * 0.62, sides), properties: { base: ht * 0.82, height: ht, color } });
    }
  }
  return { type: "FeatureCollection", features: out };
}

/** Which build phases have started by `year`, as text for the slider. */
export function yearLabel(year: number, phaseYears: [number, number, number]): string {
  if (year === TODAY) return "Today";
  const started = phaseYears.filter((y) => y <= year).length;
  const phase = started ? `phase ${started} built` : "before building";
  return `Year ${year} · ${phase}`;
}

// ---- Camera path ------------------------------------------------------------------------------------------

/** Catmull-Rom through the keyframes, so the camera glides through each point instead of stopping. Bearings are
 * unwrapped so a turn from 350° to 10° goes the short way. */
export function cameraPath(points: Camera[]) {
  const bearings: number[] = [];
  for (const p of points) {
    const prev = bearings[bearings.length - 1];
    let b = p.bearing;
    if (prev !== undefined) while (b - prev > 180) b -= 360;
    if (prev !== undefined) while (b - prev < -180) b += 360;
    bearings.push(b);
  }
  const keys = points.map((p, i) => [p.center[0], p.center[1], p.zoom, p.pitch, bearings[i]]);
  const starts: number[] = [0];
  for (let i = 1; i < points.length; i++) starts.push(starts[i - 1] + points[i].duration_s);
  const total = starts[starts.length - 1];

  function at(t: number): { center: [number, number]; zoom: number; pitch: number; bearing: number } {
    const time = Math.min(Math.max(t, 0), total);
    let i = 1;
    while (i < points.length - 1 && starts[i] < time) i++;
    const seg = points.length > 1 ? (time - starts[i - 1]) / (starts[i] - starts[i - 1] || 1) : 0;
    const u = ease(seg, i === 1, i === points.length - 1);
    const p0 = keys[Math.max(i - 2, 0)];
    const p1 = keys[i - 1];
    const p2 = keys[Math.min(i, keys.length - 1)];
    const p3 = keys[Math.min(i + 1, keys.length - 1)];
    const v = p1.map((_, d) => catmull(p0[d], p1[d], p2[d], p3[d], u));
    return { center: [v[0], v[1]], zoom: v[2], pitch: Math.min(Math.max(v[3], 0), 85), bearing: v[4] };
  }
  return { total, at };
}

/** Ease in on the first segment and out on the last; constant speed in between. */
function ease(t: number, first: boolean, last: boolean): number {
  if (first && last) return t * t * (3 - 2 * t);
  if (first) return t * t * (2 - t); // speed 0 → 1
  if (last) return t * (1 + t * (1 - t)); // speed 1 → 0
  return t;
}

function catmull(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}
