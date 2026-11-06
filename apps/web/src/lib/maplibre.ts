"use client";
// Shared MapLibre setup: worker URL, the monochrome default style, and the optional satellite basemap.
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";

let workerSet = false;
export function ensureMaplibre() {
  if (!workerSet && typeof window !== "undefined") {
    maplibregl.setWorkerUrl(new URL("/vendor/maplibre-gl-worker.mjs", window.location.origin).href);
    workerSet = true;
  }
  return maplibregl;
}

/** Aerial basemap. Default: USGS National Map imagery (public domain, US coverage). */
export const SATELLITE_TILES =
  process.env.NEXT_PUBLIC_SATELLITE_TILES ||
  "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}";
export const SATELLITE_ATTRIBUTION = process.env.NEXT_PUBLIC_SATELLITE_TILES ? "" : "Imagery: USGS The National Map";

/** Default style: black background only. No third-party tiles, no glyph server. */
export function baseStyle(): StyleSpecification {
  const style: StyleSpecification = {
    version: 8,
    sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#000000" } }],
  };
  if (SATELLITE_TILES) {
    style.sources.satellite = {
      type: "raster",
      tiles: [SATELLITE_TILES],
      tileSize: 256,
      maxzoom: 16,
      attribution: SATELLITE_ATTRIBUTION || undefined,
    };
    style.layers.push({
      id: "satellite",
      type: "raster",
      source: "satellite",
      layout: { visibility: "none" },
      paint: { "raster-opacity": 0.9 },
    });
  }
  return style;
}

export function setSatelliteVisible(map: maplibregl.Map, visible: boolean) {
  if (map.getLayer("satellite")) map.setLayoutProperty("satellite", "visibility", visible ? "visible" : "none");
}
