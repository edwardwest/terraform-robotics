"use client";
import { useEffect, useRef, useState } from "react";
import type { Feature, FeatureCollection, LineString, Point, Polygon } from "geojson";
import type { GeoJSONSource, Marker } from "maplibre-gl";
import type { FlowProps, KeypointProps, LayerName, Project, TerrainSummary } from "@/lib/api";
import { ensureMaplibre, SATELLITE_TILES, setSatelliteVisible } from "@/lib/maplibre";
import { useMap } from "@/lib/useMap";
import { emptyFC, polygonFeature } from "@/lib/geo";
import { IconMap, IconMinus, IconPlus, IconRotate3d, IconRuler } from "../Icons";
import { analysisLayers, boundaryLayers, LAYER_IDS, sectionLayers, type ToggleKey } from "./layers";
import styles from "./TerrainMap.module.css";

export type LayerData = Partial<Record<LayerName, FeatureCollection>>;

interface Props {
  project: Project | null;
  summary: TerrainSummary | null;
  data: LayerData;
  visible: Record<ToggleKey, boolean>;
  sectionMode: boolean;
  section: [number, number][];
  onSectionClick: (lngLat: [number, number]) => void;
  onStartSection: () => void;
  selectedKeypoint: string | null;
  onSelectKeypoint: (id: string) => void;
}

/** Mark the highest-order streams as main flow. */
function tagMainFlow(fc: FeatureCollection): FeatureCollection {
  const feats = fc.features as Feature<LineString, FlowProps>[];
  const maxOrder = feats.reduce((m, f) => Math.max(m, Number(f.properties?.order ?? 0)), 0);
  const threshold = maxOrder >= 3 ? maxOrder - 1 : maxOrder;
  return {
    ...fc,
    features: feats.map((f) => ({
      ...f,
      properties: { ...f.properties, _main: Number(f.properties?.order ?? 0) >= threshold && maxOrder > 0 },
    })),
  };
}

export function TerrainMap({
  project,
  summary,
  data,
  visible,
  sectionMode,
  section,
  onSectionClick,
  onStartSection,
  selectedKeypoint,
  onSelectKeypoint,
}: Props) {
  const { containerRef, map, error } = useMap();
  const [pitched, setPitched] = useState(false);
  const [satellite, setSatellite] = useState(false);
  const markers = useRef<Map<string, { marker: Marker; el: HTMLButtonElement }>>(new Map());
  const sectionModeRef = useRef(sectionMode);
  sectionModeRef.current = sectionMode;
  const onSectionClickRef = useRef(onSectionClick);
  onSectionClickRef.current = onSectionClick;
  const onSelectRef = useRef(onSelectKeypoint);
  onSelectRef.current = onSelectKeypoint;

  // Sources and layers, added once.
  useEffect(() => {
    if (!map) return;
    for (const id of ["boundary", "contours", "flow", "valleys", "ridges", "section"]) {
      if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: emptyFC() });
    }
    for (const l of [...analysisLayers, ...boundaryLayers, ...sectionLayers]) if (!map.getLayer(l.id)) map.addLayer(l);
    const click = (e: { lngLat: { lng: number; lat: number } }) => {
      if (sectionModeRef.current) onSectionClickRef.current([e.lngLat.lng, e.lngLat.lat]);
    };
    map.on("click", click);
    return () => {
      map.off("click", click);
    };
  }, [map]);

  // Boundary + fit.
  useEffect(() => {
    if (!map || !project) return;
    (map.getSource("boundary") as GeoJSONSource | undefined)?.setData(polygonFeature(project.boundary as Polygon));
    const [a, b, c, d] = project.bbox;
    map.fitBounds([a, b, c, d], { padding: 48, duration: 0, maxZoom: 18 });
  }, [map, project]);

  // Analysis layer data.
  useEffect(() => {
    if (!map) return;
    for (const name of ["contours", "valleys", "ridges"] as const) {
      (map.getSource(name) as GeoJSONSource | undefined)?.setData(data[name] ?? emptyFC());
    }
    (map.getSource("flow") as GeoJSONSource | undefined)?.setData(data.flow ? tagMainFlow(data.flow) : emptyFC());
  }, [map, data.contours, data.flow, data.valleys, data.ridges]);

  // Keypoints as HTML markers (no glyph server needed for "K1" labels).
  useEffect(() => {
    if (!map) return;
    const maplibregl = ensureMaplibre();
    const fc = data.keypoints as FeatureCollection<Point, KeypointProps> | undefined;
    const seen = new Set<string>();
    for (const f of fc?.features ?? []) {
      const id = f.properties.id;
      seen.add(id);
      let entry = markers.current.get(id);
      if (!entry) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = styles.keypoint;
        el.innerHTML = `<span class="${styles.diamond}"></span><span class="${styles.kpLabel}"></span>`;
        el.addEventListener("click", (ev) => {
          ev.stopPropagation();
          onSelectRef.current(id);
        });
        const marker = new maplibregl.Marker({ element: el, anchor: "left", offset: [-22, 0] }).setLngLat(f.geometry.coordinates as [number, number]).addTo(map);
        entry = { marker, el };
        markers.current.set(id, entry);
      }
      entry.marker.setLngLat(f.geometry.coordinates as [number, number]);
      (entry.el.querySelector(`.${styles.kpLabel}`) as HTMLElement).textContent = id;
      entry.el.setAttribute("aria-label", `Keypoint ${id}${f.properties.confirmed ? ", confirmed" : ""}`);
      entry.el.dataset.confirmed = String(!!f.properties.confirmed);
    }
    for (const [id, entry] of markers.current) {
      if (!seen.has(id)) {
        entry.marker.remove();
        markers.current.delete(id);
      }
    }
  }, [map, data.keypoints]);

  useEffect(() => {
    for (const [id, { el }] of markers.current) {
      el.dataset.selected = String(id === selectedKeypoint);
      el.style.display = visible.keypoints ? "" : "none";
    }
  }, [selectedKeypoint, visible.keypoints, data.keypoints]);

  useEffect(() => {
    const m = markers.current;
    return () => {
      for (const { marker } of m.values()) marker.remove();
      m.clear();
    };
  }, []);

  // Optional raster-dem for hillshade and 3D terrain, only when the API provides a tiles URL.
  useEffect(() => {
    if (!map || !summary?.dem_tiles_url) return;
    if (!map.getSource("dem")) {
      map.addSource("dem", { type: "raster-dem", tiles: [summary.dem_tiles_url], tileSize: 256, encoding: "terrarium" });
      map.addLayer(
        {
          id: "hillshade",
          type: "hillshade",
          source: "dem",
          paint: {
            "hillshade-shadow-color": "#000000",
            "hillshade-highlight-color": "#ffffff",
            "hillshade-accent-color": "#000000",
            "hillshade-exaggeration": 0.35,
          },
        },
        "contours-minor",
      );
    }
  }, [map, summary?.dem_tiles_url]);

  // Visibility toggles.
  useEffect(() => {
    if (!map) return;
    for (const [key, ids] of Object.entries(LAYER_IDS)) {
      for (const id of ids) {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible[key as ToggleKey] ? "visible" : "none");
      }
    }
  }, [map, visible, summary?.dem_tiles_url]);

  // Section line.
  useEffect(() => {
    if (!map) return;
    const features: Feature[] = section.map((c) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: c } }));
    if (section.length === 2) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: section } });
    (map.getSource("section") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
  }, [map, section]);

  useEffect(() => {
    if (map) map.getCanvas().style.cursor = sectionMode ? "crosshair" : "";
  }, [map, sectionMode]);

  const toggle3d = () => {
    if (!map) return;
    const next = !pitched;
    setPitched(next);
    if (summary?.dem_tiles_url && map.getSource("dem")) map.setTerrain(next ? { source: "dem", exaggeration: 1.5 } : null);
    map.easeTo({ pitch: next ? 60 : 0, bearing: next ? -20 : 0, duration: 600 });
  };

  const toggleSatellite = () => {
    if (!map) return;
    setSatelliteVisible(map, !satellite);
    setSatellite(!satellite);
  };

  return (
    <div className={styles.wrap}>
      <div ref={containerRef} className={styles.map} role="region" aria-label="Terrain map" />
      <div className={styles.topbar}>
        <button type="button" className="chip" aria-pressed={sectionMode} onClick={onStartSection} disabled={!map}>
          <IconRuler size={16} /> {sectionMode ? (section.length === 1 ? "Click the end point" : "Click the start point") : "Draw section"}
        </button>
        {SATELLITE_TILES && (
          <button type="button" className="chip" aria-pressed={satellite} onClick={toggleSatellite} disabled={!map}>
            <IconMap size={16} /> Basemap
          </button>
        )}
      </div>
      <div className={styles.controls}>
        <button type="button" className="icon-btn" aria-label="Zoom in" onClick={() => map?.zoomIn()}>
          <IconPlus />
        </button>
        <button type="button" className="icon-btn" aria-label="Zoom out" onClick={() => map?.zoomOut()}>
          <IconMinus />
        </button>
        <button type="button" className="chip" aria-pressed={pitched} onClick={toggle3d}>
          <IconRotate3d size={16} /> {pitched ? "Flat view" : "Tilt to 3D"}
        </button>
      </div>
      {error && <p className={`error-text ${styles.err}`} role="alert">{error}</p>}
    </div>
  );
}
