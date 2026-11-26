"use client";
// 3D view: the master plan on the terrain, with a year slider that builds the phases and grows the trees, and a
// fly-through path that plays in the browser and records to a video file. MapLibre fill-extrusions on 3D terrain;
// no 3D engine. Sizes over time are estimates (tr_kb.growth); the panel says so.
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FeatureCollection } from "geojson";
import type { FilterSpecification, GeoJSONSource, Map as MLMap } from "maplibre-gl";
import { api, type Camera, type PlanScene, type PlanSiteSettings, type Project, type TerrainSummary } from "@/lib/api";
import { setSatelliteVisible } from "@/lib/maplibre";
import { useMap } from "@/lib/useMap";
import { IconArrowLeft, IconPlay, IconPlus, IconRecord, IconStop, IconX } from "../Icons";
import { cameraPath, MAX_YEAR, TODAY, treesAt, yearLabel } from "./sceneGeometry";
import styles from "./Scene.module.css";

const EMPTY = { type: "FeatureCollection" as const, features: [] };
const DURATIONS = [3, 5, 8, 12];

export function SceneView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<TerrainSummary | null>(null);
  const [scene, setScene] = useState<PlanScene | null>(null);
  const [settings, setSettings] = useState<PlanSiteSettings | null>(null);
  const [year, setYear] = useState(10);
  const [mode, setMode] = useState<"idle" | "playing" | "recording">("idle");
  const [grow, setGrow] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { containerRef, map, error: mapError } = useMap({ pitch: 60, bearing: -20 });
  const stopRef = useRef(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fitted = useRef(false);

  const load = useCallback(async () => {
    try {
      const [p, t, s, site] = await Promise.all([
        api.getProject(projectId), api.getTerrain(projectId), api.getPlanScene(projectId), api.getPlanSite(projectId),
      ]);
      setProject(p);
      setSummary(t);
      setScene(s);
      setSettings(site.settings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The 3D view couldn't load.");
    }
  }, [projectId]);
  useEffect(() => void load(), [load]);

  // Base: aerial photo draped on the terrain model, a soft sky, and the property line.
  useEffect(() => {
    if (!map || !project) return;
    setSatelliteVisible(map, true);
    if (summary?.dem_tiles_url && !map.getSource("dem")) {
      map.addSource("dem", {
        type: "raster-dem", tiles: [summary.dem_tiles_url], tileSize: 256, encoding: "terrarium", minzoom: 8, maxzoom: 16,
        bounds: summary.dem_bounds ?? undefined,
      });
      map.setTerrain({ source: "dem", exaggeration: 1.2 });
      map.addLayer({ id: "hillshade", type: "hillshade", source: "dem", paint: { "hillshade-exaggeration": 0.2, "hillshade-shadow-color": "#000000" } });
    }
    try {
      map.setSky({ "sky-color": "#b9c6cf", "horizon-color": "#e6e9ea", "fog-color": "#e6e9ea", "sky-horizon-blend": 0.6, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.85 });
    } catch {
      /* older styles without sky support */
    }
    if (!map.getSource("boundary")) {
      map.addSource("boundary", { type: "geojson", data: { type: "Feature", geometry: project.boundary, properties: {} } });
      map.addLayer({ id: "boundary", type: "line", source: "boundary", paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.8, "line-dasharray": [3, 2] } });
    }
    if (!fitted.current) {
      fitted.current = true;
      const [w, s, e, n] = project.bbox;
      map.fitBounds([[w, s], [e, n]], { padding: 60, pitch: 60, bearing: -20, duration: 0 });
    }
  }, [map, project, summary?.dem_tiles_url, summary?.dem_bounds]);

  // Plan layers.
  useEffect(() => {
    if (!map || !scene) return;
    const add = (id: string, data: FeatureCollection) => {
      const src = map.getSource(id) as GeoJSONSource | undefined;
      if (src) src.setData(data);
      else map.addSource(id, { type: "geojson", data });
    };
    add("scene-areas", scene.areas);
    add("scene-buildings", scene.buildings);
    add("scene-trees", EMPTY);
    if (!map.getLayer("scene-areas")) {
      map.addLayer({ id: "scene-areas", type: "fill", source: "scene-areas", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.38 } });
      const extrude = (id: string) => map.addLayer({
        id, type: "fill-extrusion", source: id,
        paint: {
          "fill-extrusion-color": ["get", "color"],
          "fill-extrusion-height": ["get", id === "scene-trees" ? "height" : "height_m"],
          "fill-extrusion-base": ["coalesce", ["get", id === "scene-trees" ? "base" : "base_m"], 0],
          "fill-extrusion-vertical-gradient": true,
        },
      });
      extrude("scene-buildings");
      extrude("scene-trees");
    }
  }, [map, scene]);

  // The year: what's built, and how big the trees are. Fractional years (during a fly-through) round to a fifth.
  const shownYear = Math.round(year * 5) / 5;
  const trees = useMemo(() => (scene ? treesAt(scene, shownYear) : null), [scene, shownYear]);
  useEffect(() => {
    if (!map || !trees || !map.getSource("scene-trees")) return;
    (map.getSource("scene-trees") as GeoJSONSource).setData(trees);
    const filter: FilterSpecification = shownYear === TODAY ? ["==", ["get", "status"], "existing"] : ["<=", ["get", "year"], shownYear];
    for (const id of ["scene-areas", "scene-buildings"]) if (map.getLayer(id)) map.setFilter(id, filter);
  }, [map, trees, shownYear]);

  // ---- Settings (phase years, flight) save as they change --------------------------------------------------
  const save = useCallback((next: PlanSiteSettings, reloadScene = false) => {
    setSettings(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        await api.putPlanSite(projectId, next);
        if (reloadScene) setScene(await api.getPlanScene(projectId));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't save.");
      }
    }, 500);
  }, [projectId]);

  const flight = settings?.flight ?? [];
  const addView = () => {
    if (!map || !settings || flight.length >= 12) return;
    const c = map.getCenter();
    const cam: Camera = {
      center: [round(c.lng, 7), round(c.lat, 7)], zoom: round(map.getZoom(), 2), pitch: round(map.getPitch(), 1),
      bearing: round(map.getBearing(), 1), duration_s: flight.length ? 5 : 1,
    };
    save({ ...settings, flight: [...flight, cam] });
  };
  const goTo = (cam: Camera) => map?.easeTo({ center: cam.center, zoom: cam.zoom, pitch: cam.pitch, bearing: cam.bearing, duration: 800 });

  // ---- Fly-through ----------------------------------------------------------------------------------------
  const fly = useCallback(async (record: boolean) => {
    if (!map || flight.length < 2 || !scene) return;
    stopRef.current = false;
    const path = cameraPath(flight);
    const startYear = grow ? TODAY : year;
    const endYear = grow ? MAX_YEAR - 10 : year;
    map.jumpTo(path.at(0));
    if (grow) setYear(startYear);
    setMode(record ? "recording" : "playing");
    setStatus("Loading the scene…");
    await idle(map, 8000);

    let recorder: MediaRecorder | null = null;
    let onRender: (() => void) | null = null;
    const chunks: Blob[] = [];
    let mime = "";
    if (record) {
      mime = ["video/mp4;codecs=avc1", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) ?? "";
      // Frames are taken explicitly right after each map render; automatic capture skips frames when the
      // browser is busy compositing, which cut recordings short.
      const stream = map.getCanvas().captureStream(0);
      const track = stream.getVideoTracks()[0] as CanvasCaptureMediaStreamTrack;
      onRender = () => track.requestFrame();
      map.on("render", onRender);
      recorder = new MediaRecorder(stream, { mimeType: mime || undefined, videoBitsPerSecond: 10_000_000 });
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.start(1000);
    }
    setStatus(record ? "Recording…" : null);

    const t0 = performance.now();
    await new Promise<void>((resolve) => {
      const frame = () => {
        const t = (performance.now() - t0) / 1000;
        if (stopRef.current || t > path.total + 1) return resolve();
        map.jumpTo(path.at(t));
        map.triggerRepaint();
        if (grow) setYear(startYear + (endYear - startYear) * Math.min(t / path.total, 1));
        requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    });

    if (recorder) {
      if (onRender) map.off("render", onRender);
      await new Promise<void>((resolve) => {
        recorder!.onstop = () => resolve();
        recorder!.stop();
      });
      if (!stopRef.current && chunks.length) {
        const ext = mime.startsWith("video/mp4") ? "mp4" : "webm";
        const url = URL.createObjectURL(new Blob(chunks, { type: mime || "video/webm" }));
        const a = document.createElement("a");
        a.href = url;
        a.download = `${slug(project?.name ?? "site")}-fly-through.${ext}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
        setStatus(`Saved a ${ext.toUpperCase()} video to your downloads.`);
      } else {
        setStatus(null);
      }
    }
    if (grow) setYear(endYear);
    setMode("idle");
  }, [map, flight, scene, grow, year, project?.name]);

  const busy = mode !== "idle";
  const phaseYears = settings?.phase_years ?? [0, 2, 4];

  return (
    <div className={styles.layout}>
      <aside className={styles.controls} aria-label="3D view settings">
        <div className={styles.intro}>
          <Link href={`/projects/${projectId}/design?mode=plan`} className={`app-small ${styles.back}`}>
            <IconArrowLeft size={14} /> Master plan
          </Link>
          <p className="app-eyebrow">{project ? `${project.name} · ` : ""}3D view</p>
          <h1 className="app-display">See it grow.</h1>
          <p className="app-body">Drag to orbit, scroll to zoom. Move through the years to watch the phases go in and the trees fill out.</p>
        </div>

        {scene && settings && (
          <>
            <div className="field">
              <label className="field-label" htmlFor="sc-year">{yearLabel(shownYear, phaseYears)}</label>
              <input id="sc-year" type="range" className={styles.range} min={TODAY} max={MAX_YEAR} step={1} value={Math.round(year)}
                disabled={busy} onChange={(e) => setYear(Number(e.target.value))} />
              <div className={styles.scale}><span className="app-small">Today</span><span className="app-small">Year {MAX_YEAR}</span></div>
            </div>

            <fieldset className={styles.group}>
              <legend className="field-label">Phase start years</legend>
              <div className={styles.phases}>
                {phaseYears.map((y, i) => (
                  <label key={i} className={styles.phase}>
                    <span className="app-small">Phase {i + 1}</span>
                    <input className="input" type="number" min={0} max={50} value={y} disabled={busy}
                      onChange={(e) => {
                        const next = [...phaseYears] as [number, number, number];
                        next[i] = Math.max(0, Math.min(50, Number(e.target.value) || 0));
                        for (let j = i + 1; j < 3; j++) next[j] = Math.max(next[j], next[i]);
                        for (let j = i - 1; j >= 0; j--) next[j] = Math.min(next[j], next[i]);
                        save({ ...settings, phase_years: next }, true);
                      }} />
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className={styles.group}>
              <legend className="field-label">Fly-through</legend>
              <p className="app-small">Frame a view and add it. The camera glides through the views in order.</p>
              {flight.length > 0 && (
                <ol className={styles.views}>
                  {flight.map((cam, i) => (
                    <li key={i} className={styles.view}>
                      <button type="button" className={styles.linkBtn} onClick={() => goTo(cam)} disabled={busy}>View {i + 1}</button>
                      {i > 0 ? (
                        <select className="input" aria-label={`Seconds to reach view ${i + 1}`} value={cam.duration_s} disabled={busy}
                          onChange={(e) => save({ ...settings, flight: flight.map((c, j) => (j === i ? { ...c, duration_s: Number(e.target.value) } : c)) })}>
                          {[...new Set([...DURATIONS, cam.duration_s])].sort((a, b) => a - b).map((d) => <option key={d} value={d}>{d} s</option>)}
                        </select>
                      ) : <span className="app-small">Start</span>}
                      <button type="button" className="icon-btn" aria-label={`Remove view ${i + 1}`} disabled={busy}
                        onClick={() => save({ ...settings, flight: flight.filter((_, j) => j !== i) })}><IconX size={14} /></button>
                    </li>
                  ))}
                </ol>
              )}
              <button type="button" className="btn btn-sm" onClick={addView} disabled={busy || flight.length >= 12}>
                <IconPlus size={14} /> Add this view
              </button>
              <label className={styles.check}>
                <input type="checkbox" checked={grow} disabled={busy} onChange={(e) => setGrow(e.target.checked)} />
                <span className="app-small">Grow from today to year {MAX_YEAR - 10} during the flight</span>
              </label>
              <div className={styles.chips}>
                {busy ? (
                  <button type="button" className="btn btn-primary" onClick={() => (stopRef.current = true)}><IconStop size={16} /> Stop</button>
                ) : (
                  <>
                    <button type="button" className="btn" onClick={() => fly(false)} disabled={flight.length < 2}><IconPlay size={16} /> Play</button>
                    <button type="button" className="btn btn-primary" onClick={() => fly(true)} disabled={flight.length < 2}><IconRecord size={16} /> Record video</button>
                  </>
                )}
              </div>
              {flight.length < 2 && <p className="app-small">Add at least two views to play or record.</p>}
              {status && <p className="app-small" role="status">{status}</p>}
            </fieldset>

            <p className="app-small">
              Tree sizes are estimates from USDA PLANTS mature heights and growth rates, or typical sizes where a species has no data.
              {scene.trees_thinned ? " Large plantings show a thinned sample of their trees." : ""}
              {!scene.terrain ? " This project has no terrain model yet, so the land is drawn flat." : ""}
            </p>
          </>
        )}
        {(error || mapError) && <p className="error-text" role="alert">{error ?? mapError}</p>}
      </aside>
      <div className={styles.mapCol}>
        <div ref={containerRef} className={styles.map} />
      </div>
    </div>
  );
}

function idle(map: MLMap, timeoutMs: number) {
  return new Promise<void>((resolve) => {
    const t = setTimeout(resolve, timeoutMs);
    map.once("idle", () => {
      clearTimeout(t);
      resolve();
    });
    map.triggerRepaint();
  });
}

const round = (v: number, d: number) => Math.round(v * 10 ** d) / 10 ** d;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "site";
