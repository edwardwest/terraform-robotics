import turfArea from "@turf/area";
import turfLength from "@turf/length";
import type { Feature, FeatureCollection, Geometry, LineString, Polygon, Position } from "geojson";

export function polygonAreaM2(poly: Polygon | null): number | null {
  if (!poly) return null;
  return turfArea({ type: "Feature", properties: {}, geometry: poly });
}

export function polygonPerimeterM(poly: Polygon | null): number | null {
  if (!poly) return null;
  const ring: LineString = { type: "LineString", coordinates: poly.coordinates[0] };
  return turfLength({ type: "Feature", properties: {}, geometry: ring }, { units: "kilometers" }) * 1000;
}

export function bboxOf(coords: Position[]): [number, number, number, number] {
  let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
  for (const [x, y] of coords) {
    if (x < a) a = x;
    if (y < b) b = y;
    if (x > c) c = x;
    if (y > d) d = y;
  }
  return [a, b, c, d];
}

function closeRing(ring: Position[]): Position[] {
  if (ring.length < 3) return ring;
  const [f, l] = [ring[0], ring[ring.length - 1]];
  return f[0] === l[0] && f[1] === l[1] ? ring : [...ring, f];
}

/**
 * Pull the first polygon out of user-supplied GeoJSON (Polygon, MultiPolygon, Feature, FeatureCollection).
 * MultiPolygon: takes the largest part. Throws a readable message when nothing usable is found.
 */
export function extractPolygon(input: unknown): Polygon {
  const geoms: Geometry[] = [];
  const visit = (g: unknown) => {
    if (!g || typeof g !== "object") return;
    const o = g as { type?: string; features?: unknown[]; geometry?: unknown; geometries?: unknown[] };
    if (o.type === "FeatureCollection" && Array.isArray(o.features)) o.features.forEach(visit);
    else if (o.type === "Feature") visit(o.geometry);
    else if (o.type === "GeometryCollection" && Array.isArray(o.geometries)) o.geometries.forEach(visit);
    else if (o.type === "Polygon" || o.type === "MultiPolygon") geoms.push(o as Geometry);
  };
  visit(input);
  const polys: Polygon[] = [];
  for (const g of geoms) {
    if (g.type === "Polygon") polys.push(g);
    else if (g.type === "MultiPolygon") for (const c of g.coordinates) polys.push({ type: "Polygon", coordinates: c });
  }
  if (!polys.length) throw new Error("No polygon found in that file.");
  const best = polys.reduce((a, b) => ((polygonAreaM2(b) ?? 0) > (polygonAreaM2(a) ?? 0) ? b : a));
  const outer = closeRing(best.coordinates[0].map((p) => [p[0], p[1]]));
  if (outer.length < 4) throw new Error("That polygon has fewer than three vertices.");
  for (const [x, y] of outer) {
    if (Math.abs(x) > 180 || Math.abs(y) > 90) throw new Error("Coordinates must be longitude/latitude (EPSG:4326).");
  }
  return { type: "Polygon", coordinates: [outer] };
}

export const emptyFC = (): FeatureCollection => ({ type: "FeatureCollection", features: [] });

export const polygonFeature = (poly: Polygon): Feature<Polygon> => ({ type: "Feature", properties: {}, geometry: poly });
