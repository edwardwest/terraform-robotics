// Monochrome MapLibre layer definitions for the terrain analysis layers.
import type { LayerSpecification } from "maplibre-gl";

export type ToggleKey = "contours" | "flow" | "valleys" | "ridges" | "keypoints" | "hillshade";

export const LAYER_IDS: Record<Exclude<ToggleKey, "keypoints">, string[]> = {
  hillshade: ["hillshade"],
  contours: ["contours-minor", "contours-index"],
  valleys: ["valleys"],
  ridges: ["ridges"],
  flow: ["flow-minor", "flow-main"],
};

export const analysisLayers: LayerSpecification[] = [
  {
    id: "contours-minor",
    type: "line",
    source: "contours",
    filter: ["!=", ["get", "index"], true],
    paint: { "line-color": "rgba(255,255,255,0.13)", "line-width": 1 },
  },
  {
    id: "contours-index",
    type: "line",
    source: "contours",
    filter: ["==", ["get", "index"], true],
    paint: { "line-color": "rgba(255,255,255,0.26)", "line-width": 1.25 },
  },
  {
    id: "ridges",
    type: "line",
    source: "ridges",
    layout: { "line-cap": "round" },
    paint: { "line-color": "rgba(255,255,255,0.7)", "line-width": 1.5, "line-dasharray": [0, 2.5] },
  },
  {
    id: "valleys",
    type: "line",
    source: "valleys",
    paint: { "line-color": "rgba(255,255,255,0.7)", "line-width": 1.5, "line-dasharray": [6, 4] },
  },
  {
    id: "flow-minor",
    type: "line",
    source: "flow",
    filter: ["!=", ["get", "_main"], true],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "rgba(255,255,255,0.45)", "line-width": 1.25 },
  },
  {
    id: "flow-main",
    type: "line",
    source: "flow",
    filter: ["==", ["get", "_main"], true],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 2.5 },
  },
];

export const boundaryLayers: LayerSpecification[] = [
  {
    id: "boundary-line",
    type: "line",
    source: "boundary",
    paint: { "line-color": "#ffffff", "line-width": 2 },
  },
];

export const sectionLayers: LayerSpecification[] = [
  {
    id: "section-line",
    type: "line",
    source: "section",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [2, 2] },
  },
  {
    id: "section-points",
    type: "circle",
    source: "section",
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-radius": 5,
      "circle-color": "#000000",
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  },
];
