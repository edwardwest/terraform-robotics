"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Polygon } from "geojson";
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode, type GeoJSONStoreFeatures } from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import { useMap } from "@/lib/useMap";
import { SATELLITE_TILES, setSatelliteVisible } from "@/lib/maplibre";
import { bboxOf } from "@/lib/geo";
import { IconMap, IconPencil, IconX } from "./Icons";
import styles from "./BoundaryMap.module.css";

interface Props {
  boundary: Polygon | null;
  /** Draw mode allows creating a new polygon by clicking. */
  drawEnabled: boolean;
  onChange: (poly: Polygon | null) => void;
  flyTo?: { center: [number, number]; zoom: number } | null;
}

const round7 = (n: number) => Math.round(n * 1e7) / 1e7;
const roundPoly = (p: Polygon): Polygon => ({
  type: "Polygon",
  coordinates: [p.coordinates[0].map(([x, y]) => [round7(x), round7(y)])],
});
const samePoly = (a: Polygon | null, b: Polygon | null) => JSON.stringify(a) === JSON.stringify(b);

export function BoundaryMap({ boundary, drawEnabled, onChange, flyTo }: Props) {
  const { containerRef, map, error } = useMap();
  const drawRef = useRef<TerraDraw | null>(null);
  const lastEmitted = useRef<Polygon | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [editing, setEditing] = useState(false);
  const [satellite, setSatellite] = useState(false);
  const [drawing, setDrawing] = useState(false);
  const [drawError, setDrawError] = useState<string | null>(null);
  const [drawReady, setDrawReady] = useState(false);

  const currentPolygonId = () => {
    const f = drawRef.current?.getSnapshot().find((x) => x.geometry.type === "Polygon");
    return f?.id ?? null;
  };

  const emit = useCallback(() => {
    const draw = drawRef.current;
    if (!draw) return;
    const f = draw.getSnapshot().find((x) => x.geometry.type === "Polygon" && !x.properties?.currentlyDrawing);
    const poly = f ? roundPoly(f.geometry as Polygon) : null;
    if (samePoly(poly, lastEmitted.current)) return;
    lastEmitted.current = poly;
    onChangeRef.current(poly);
  }, []);

  // Start terra-draw once the map is ready.
  useEffect(() => {
    if (!map) return;
    let draw: TerraDraw;
    try {
      const white = "#ffffff" as const;
      draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: 7 }),
        modes: [
          new TerraDrawPolygonMode({
            styles: {
              fillColor: white,
              fillOpacity: 0.08,
              outlineColor: white,
              outlineWidth: 2,
              closingPointColor: white,
              closingPointWidth: 5,
              closingPointOutlineColor: "#000000",
              closingPointOutlineWidth: 2,
            },
          }),
          new TerraDrawSelectMode({
            flags: {
              polygon: {
                feature: {
                  draggable: false,
                  coordinates: { draggable: true, deletable: true, midpoints: true },
                },
              },
            },
            styles: {
              selectedPolygonColor: white,
              selectedPolygonFillOpacity: 0.12,
              selectedPolygonOutlineColor: white,
              selectedPolygonOutlineWidth: 2,
              selectionPointColor: "#000000",
              selectionPointWidth: 6,
              selectionPointOutlineColor: white,
              selectionPointOutlineWidth: 2,
              midPointColor: white,
              midPointWidth: 3,
              midPointOutlineColor: "#000000",
              midPointOutlineWidth: 1,
            },
          }),
        ],
      });
      draw.start();
    } catch (e) {
      setDrawError(e instanceof Error ? e.message : "Drawing tools did not start.");
      return;
    }
    drawRef.current = draw;
    setDrawReady(true);
    draw.on("finish", () => {
      emit();
      setDrawing(false);
      draw.setMode("static");
    });
    draw.on("change", (_ids, type) => {
      if (type !== "styling") emit();
    });
    return () => {
      try {
        draw.stop();
      } catch {
        /* map already removed */
      }
      drawRef.current = null;
      setDrawReady(false);
    };
  }, [map, emit]);

  // Sync external boundary (loaded project or uploaded file) into terra-draw.
  useEffect(() => {
    const draw = drawRef.current;
    if (!map || !draw) return;
    if (samePoly(boundary, lastEmitted.current) && (boundary === null) === (currentPolygonId() === null)) return;
    draw.setMode("static");
    draw.clear();
    lastEmitted.current = boundary ? roundPoly(boundary) : null;
    if (boundary) {
      const feature: GeoJSONStoreFeatures = {
        type: "Feature",
        geometry: roundPoly(boundary),
        properties: { mode: "polygon" },
      };
      const [res] = draw.addFeatures([feature]);
      if (res && !res.valid) setDrawError(`That boundary could not be shown: ${res.reason ?? "invalid geometry"}.`);
      const [a, b, c, d] = bboxOf(boundary.coordinates[0]);
      map.fitBounds([a, b, c, d], { padding: 64, duration: 0, maxZoom: 18 });
    }
    setEditing(false);
  }, [boundary, map, drawReady]);

  // Draw mode: when no polygon exists and drawing is allowed, arm the polygon tool.
  useEffect(() => {
    const draw = drawRef.current;
    if (!draw || !map) return;
    if (drawEnabled && !boundary && draw.getMode() !== "polygon") {
      draw.setMode("polygon");
      setDrawing(true);
    } else if (!drawEnabled && draw.getMode() === "polygon") {
      draw.setMode("static");
      setDrawing(false);
    }
  }, [drawEnabled, boundary, map, drawReady]);

  useEffect(() => {
    if (map && flyTo) map.flyTo({ center: flyTo.center, zoom: flyTo.zoom, duration: 800 });
  }, [map, flyTo]);

  const toggleEdit = () => {
    const draw = drawRef.current;
    const id = currentPolygonId();
    if (!draw || id == null) return;
    if (editing) {
      draw.deselectFeature(id);
      draw.setMode("static");
      setEditing(false);
    } else {
      draw.setMode("select");
      draw.selectFeature(id);
      setEditing(true);
    }
  };

  const clearBoundary = () => {
    const draw = drawRef.current;
    if (!draw) return;
    draw.setMode("static");
    draw.clear();
    setEditing(false);
    lastEmitted.current = null;
    onChangeRef.current(null);
    if (drawEnabled) {
      draw.setMode("polygon");
      setDrawing(true);
    }
  };

  const toggleSatellite = () => {
    if (!map) return;
    setSatelliteVisible(map, !satellite);
    setSatellite(!satellite);
  };

  const hasPolygon = !!boundary;

  return (
    <div className={styles.wrap}>
      <div ref={containerRef} className={styles.map} aria-label="Boundary map" role="region" />
      <div className={styles.toolbar}>
        <button
          type="button"
          className="chip"
          aria-pressed={editing}
          onClick={toggleEdit}
          disabled={!hasPolygon || !map}
        >
          <IconPencil size={16} /> Edit vertices
        </button>
        <button
          type="button"
          className="chip"
          aria-pressed={satellite}
          onClick={toggleSatellite}
          disabled={!SATELLITE_TILES || !map}
          title={SATELLITE_TILES ? undefined : "Set NEXT_PUBLIC_SATELLITE_TILES to enable imagery."}
        >
          <IconMap size={16} /> Basemap{satellite ? ": Imagery" : ""}
        </button>
        {hasPolygon && (
          <button type="button" className="chip" onClick={clearBoundary}>
            <IconX size={16} /> Clear
          </button>
        )}
      </div>
      {(drawing || editing) && (
        <p className={styles.hint} aria-live="polite">
          {drawing
            ? "Click to place corners. Click the first point to close the boundary."
            : "Drag a corner to move it. Drag a midpoint to add one. Right-click a corner to remove it."}
        </p>
      )}
      {(error || drawError) && (
        <p className={`error-text ${styles.err}`} role="alert">
          {error || drawError}
        </p>
      )}
    </div>
  );
}
