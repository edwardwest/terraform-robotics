// Monochrome MapLibre layer definitions for the terrain analysis layers.
import type { LayerSpecification } from "maplibre-gl";

export type ToggleKey = "contours" | "flow" | "valleys" | "ridges" | "keypoints" | "hillshade" | "slope";

export const LAYER_IDS: Record<Exclude<ToggleKey, "keypoints">, string[]> = {
  hillshade: ["hillshade"],
  slope: ["slope"],
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

/** Stage 2 design elements. Drafts (planning-grade terrain) are dashed. */
export const designLayers: LayerSpecification[] = [
  {
    id: "design-rip",
    type: "line",
    source: "design",
    filter: ["==", ["get", "kind"], "rip"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": "rgba(255,255,255,0.45)",
      "line-width": ["interpolate", ["linear"], ["zoom"], 14, 0.5, 17, 1.2],
    },
  },
  {
    id: "design-swale-berm",
    type: "line",
    source: "design",
    filter: ["==", ["get", "kind"], "swale"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#000000", "line-width": 9 },
  },
  {
    id: "design-swale",
    type: "line",
    source: "design",
    filter: ["==", ["get", "kind"], "swale"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 5 },
  },
  {
    id: "design-keyline-casing",
    type: "line",
    source: "design",
    filter: ["==", ["get", "kind"], "keyline"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#000000", "line-width": 7 },
  },
  {
    id: "design-keyline",
    type: "line",
    source: "design",
    filter: ["==", ["get", "kind"], "keyline"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 3.5 },
  },
  {
    id: "design-selected",
    type: "line",
    source: "design",
    filter: ["==", ["get", "id"], "__none__"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.9, "line-gap-width": 2 },
  },
  {
    id: "pending-line",
    type: "line",
    source: "pending",
    filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [2, 2] },
  },
  {
    id: "pending-points",
    type: "circle",
    source: "pending",
    filter: ["==", ["geometry-type"], "Point"],
    paint: { "circle-radius": 6, "circle-color": "#ffffff", "circle-stroke-color": "#000000", "circle-stroke-width": 2 },
  },
];

export const DESIGN_CLICK_LAYERS = ["design-keyline", "design-rip", "design-swale"];
