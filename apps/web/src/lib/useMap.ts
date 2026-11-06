"use client";
import { useEffect, useRef, useState } from "react";
import type { Map as MLMap, MapOptions } from "maplibre-gl";
import { baseStyle, ensureMaplibre } from "./maplibre";

/** Creates a MapLibre map in `container` once, and returns it after the style has loaded. */
export function useMap(opts: Omit<MapOptions, "container" | "style"> = {}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MLMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const optsRef = useRef(opts);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let m: MLMap | null = null;
    try {
      const maplibregl = ensureMaplibre();
      const created = new maplibregl.Map({
        container: el,
        style: baseStyle(),
        center: [-98.5, 39.5],
        zoom: 3,
        attributionControl: { compact: true },
        dragRotate: true,
        maxPitch: 75,
        ...optsRef.current,
      });
      m = created;
      created.addControl(new maplibregl.ScaleControl({ unit: "imperial", maxWidth: 120 }), "bottom-left");
      created.on("load", () => setMap(created));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The map could not start. WebGL may be unavailable.");
    }
    return () => {
      setMap(null);
      m?.remove();
    };
  }, []);

  return { containerRef, map, error };
}
