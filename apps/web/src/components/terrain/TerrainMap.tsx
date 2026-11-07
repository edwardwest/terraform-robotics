"use client";
import { useEffect, useRef, useState } from "react";
import type { Feature, FeatureCollection, LineString, Point, Polygon } from "geojson";
import type { GeoJSONSource, Marker } from "maplibre-gl";
import type { DesignCollection, FlowProps, KeypointProps, LayerName, Project, TerrainSummary } from "@/lib/api";
import { ensureMaplibre, SATELLITE_TILES, setSatelliteVisible } from "@/lib/maplibre";
import { useMap } from "@/lib/useMap";
import { emptyFC, polygonFeature } from "@/lib/geo";
import { IconMap, IconMinus, IconPlus, IconRotate3d, IconRuler } from "../Icons";
import { analysisLayers, boundaryLayers, DESIGN_CLICK_LAYERS, designLayers, LAYER_IDS, previewLayers, sectionLayers, type ToggleKey } from "./layers";
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
  /** Stage 2 design elements to draw over the terrain. */
  design?: DesignCollection | null;
  selectedElement?: string | null;
  onSelectElement?: (id: string | null) => void;
  /** When set, map clicks go to `onMapClick` (e.g. placing a swale) instead of selecting. */
  mapClickActive?: boolean;
  onMapClick?: (lngLat: [number, number]) => void;
  pending?: [number, number][];
  /** Draft geometry to preview (assistant proposals). */
  preview?: FeatureCollection | null;
  /** Label for the map's own section-drawing chip; hidden when false. */
  showSectionTool?: boolean;
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
  design = null,
  selectedElement = null,
  onSelectElement,
  mapClickActive = false,
  onMapClick,
  pending = [],
  preview = null,
  showSectionTool = true,
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
  const mapClickRef = useRef({ active: mapClickActive, fn: onMapClick, select: onSelectElement });
  mapClickRef.current = { active: mapClickActive, fn: onMapClick, select: onSelectElement };

  // Sources and layers, added once.
  useEffect(() => {
    if (!map) return;
    for (const id of ["boundary", "contours", "flow", "valleys", "ridges", "section", "design", "pending", "preview"]) {
      if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: emptyFC() });
    }
    for (const l of [...analysisLayers, ...boundaryLayers, ...designLayers, ...previewLayers, ...sectionLayers]) if (!map.getLayer(l.id)) map.addLayer(l);
    const click = (e: { lngLat: { lng: number; lat: number }; point: { x: number; y: number } }) => {
      const lngLat: [number, number] = [e.lngLat.lng, e.lngLat.lat];
      if (sectionModeRef.current) return onSectionClickRef.current(lngLat);
      const m = mapClickRef.current;
      if (m.active && m.fn) return m.fn(lngLat);
      if (m.select) {
        const { x, y } = e.point;
        const hits = map.queryRenderedFeatures([[x - 4, y - 4], [x + 4, y + 4]], { layers: DESIGN_CLICK_LAYERS });
        m.select(hits.length ? String(hits[0].properties?.id) : null);
      }
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

  // Design elements; rip lines with notes are drawn a little brighter.
  useEffect(() => {
    if (!map) return;
    const fc = design
      ? { ...design, features: design.features.map((f) => ({ ...f, properties: { ...f.properties, _flag: !!f.properties.notes?.length } })) }
      : emptyFC();
    (map.getSource("design") as GeoJSONSource | undefined)?.setData(fc as FeatureCollection);
  }, [map, design]);

  useEffect(() => {
    if (map?.getLayer("design-selected")) map.setFilter("design-selected", ["==", ["get", "id"], selectedElement ?? "__none__"]);
  }, [map, selectedElement]);

  useEffect(() => {
    (map?.getSource("preview") as GeoJSONSource | undefined)?.setData(preview ?? emptyFC());
  }, [map, preview]);

  useEffect(() => {
    if (!map) return;
    const features: Feature[] = pending.map((c) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: c } }));
    (map.getSource("pending") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
  }, [map, pending]);

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

  // Elevation tiles drive hillshade and 3D terrain; slope classes are a separate raster.
  useEffect(() => {
    if (!map || !summary?.dem_tiles_url) return;
    const bounds = summary.dem_bounds ?? undefined;
    if (summary.slope_tiles_url && !map.getSource("slope")) {
      map.addSource("slope", { type: "raster", tiles: [summary.slope_tiles_url], tileSize: 256, maxzoom: 17, bounds });
      map.addLayer({ id: "slope", type: "raster", source: "slope", paint: { "raster-opacity": 0.8 } }, "contours-minor");
    }
    if (!map.getSource("dem")) {
      // Below zoom 8 the model is smaller than a pixel, so don't request those tiles.
      map.addSource("dem", { type: "raster-dem", tiles: [summary.dem_tiles_url], tileSize: 256, encoding: "terrarium", minzoom: 8, maxzoom: 16, bounds });
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

  useEffect(() => {
    if (map) map.getCanvas().style.cursor = sectionMode || mapClickActive ? "crosshair" : "";
  }, [map, sectionMode, mapClickActive]);

  // Section line.
  useEffect(() => {
    if (!map) return;
    const features: Feature[] = section.map((c) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: c } }));
    if (section.length === 2) features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: section } });
    (map.getSource("section") as GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features });
  }, [map, section]);

  const toggle3d = () => {
    if (!map) return;
    const next = !pitched;
    setPitched(next);
    if (summary?.dem_tiles_url) {
      // 3D terrain gets its own source; sharing the hillshade's source lowers rendering quality in MapLibre.
      if (next && !map.getSource("dem-terrain")) {
        map.addSource("dem-terrain", {
          type: "raster-dem", tiles: [summary.dem_tiles_url], tileSize: 256, encoding: "terrarium", minzoom: 8, maxzoom: 16,
          bounds: summary.dem_bounds ?? undefined,
        });
      }
      map.setTerrain(next ? { source: "dem-terrain", exaggeration: 1.5 } : null);
    }
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
        {showSectionTool && (
          <button type="button" className="chip" aria-pressed={sectionMode} onClick={onStartSection} disabled={!map}>
            <IconRuler size={16} /> {sectionMode ? (section.length === 1 ? "Click the end point" : "Click the start point") : "Draw section"}
          </button>
        )}
        {SATELLITE_TILES && (
          <button type="button" className="chip" aria-pressed={satellite} onClick={toggleSatellite} disabled={!map}>
            <IconMap size={16} /> Aerial
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
