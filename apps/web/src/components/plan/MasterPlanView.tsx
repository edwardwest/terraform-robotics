"use client";
// Design step, Master plan mode: place features (ponds, orchards, buildings, roads...) on the map, classified by a
// fixed set of categories with map colors from the feature library. Features that place a plan intervention are
// measured and carried into the estimate. Drawing uses terra-draw on the shared terrain map.
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FeatureCollection } from "geojson";
import type { Map as MLMap } from "maplibre-gl";
import {
  TerraDraw, TerraDrawLineStringMode, TerraDrawPointMode, TerraDrawPolygonMode, TerraDrawSelectMode,
  type GeoJSONStoreFeatures,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import {
  api, type LayerName, type PlanChecks, type PlanFeature, type PlanFeatureCollection, type PlanFeatureType, type PlanGeometry,
  type PlanItem, type PlanLibrary, type PlanSite, type PlantingCollection, type Project, type TerrainSummary,
} from "@/lib/api";
import { useAssistantPage } from "@/lib/assistant";
import { announceChange, PROJECT_CHANGED, stepCount, type ProjectChange } from "@/lib/steps";
import { IconArrowRight, IconX } from "../Icons";
import type { LayerData } from "../terrain/TerrainMap";
import tv from "../terrain/TerrainView.module.css";
import { DesignModeSwitch } from "../design/DesignModeSwitch";
import { ChecksPanel } from "./ChecksPanel";
import { FeatureProperties } from "./FeatureProperties";
import { SitePanel } from "./SitePanel";
import { formatArea, formatLength } from "./format";
import styles from "./MasterPlan.module.css";

const TerrainMap = dynamic(() => import("../terrain/TerrainMap").then((m) => m.TerrainMap), {
  ssr: false,
  loading: () => <div className={tv.mapLoading} aria-hidden="true" />,
});

const DRAW_MODE = { point: "point", line: "linestring", polygon: "polygon" } as const;
type Hex = `#${string}`;

export function MasterPlanView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<TerrainSummary | null | undefined>(undefined);
  const [data, setData] = useState<LayerData>({});
  const [library, setLibrary] = useState<PlanLibrary | null>(null);
  const [features, setFeatures] = useState<PlanFeatureCollection | null>(null);
  const [plan, setPlan] = useState<PlanItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [selected, setSelected] = useState<string | null>(null);
  const [drawType, setDrawType] = useState<PlanFeatureType | null>(null);
  const [editing, setEditing] = useState<string | null>(null); // feature id whose shape is being edited
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [phase, setPhase] = useState<0 | 1 | 2 | 3>(0);
  const [showExisting, setShowExisting] = useState(true);
  const [planting, setPlanting] = useState<PlantingCollection | null>(null);
  const [showPlanting, setShowPlanting] = useState(true);
  const [site, setSite] = useState<PlanSite | null>(null);
  const [checks, setChecks] = useState<PlanChecks | null>(null);
  const [lineMode, setLineMode] = useState<"free" | "contour">("free");
  const [contourStart, setContourStart] = useState<[number, number] | null>(null);

  const [map, setMap] = useState<MLMap | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const colorRef = useRef<Hex>("#ffffff");
  const drawTypeRef = useRef<PlanFeatureType | null>(null);
  drawTypeRef.current = drawType;

  const types = useMemo(() => new Map((library?.types ?? []).map((t) => [t.id, t])), [library]);
  const categories = useMemo(() => new Map((library?.categories ?? []).map((c) => [c.id, c])), [library]);

  const refresh = useCallback(async () => {
    const [fc, p] = await Promise.all([api.listPlanFeatures(projectId), api.getPlan(projectId)]);
    setFeatures(fc);
    setPlan(p);
    // Layouts, zones (centered on the house) and checks follow the features; they can lag a moment behind.
    api.getPlanting(projectId).then(setPlanting).catch(() => undefined);
    api.getPlanSite(projectId).then(setSite).catch(() => undefined);
    api.getPlanChecks(projectId).then(setChecks).catch(() => undefined);
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
    api.getPlanLibrary().then(setLibrary).catch((e: Error) => setError(e.message));
    refresh().catch((e: Error) => setError(e.message));
    api.getTerrain(projectId).then((s) => {
      setSummary(s);
      if (!s) return;
      (["contours", "valleys", "ridges"] as LayerName[]).forEach((n) =>
        api.getLayer(projectId, n).then((fc) => setData((d) => ({ ...d, [n]: fc as FeatureCollection }))).catch(() => undefined),
      );
    }).catch(() => setSummary(null));
  }, [projectId, refresh]);

  // Plan changed elsewhere (Ideas step in another tab, the assistant): reload the "To place" list.
  useEffect(() => {
    const on = (e: Event) => {
      if ((e as CustomEvent<ProjectChange>).detail === "plan") api.getPlan(projectId).then(setPlan).catch(() => undefined);
    };
    window.addEventListener(PROJECT_CHANGED, on);
    return () => window.removeEventListener(PROJECT_CHANGED, on);
  }, [projectId]);

  const all = useMemo(() => features?.features ?? [], [features]);
  const selectedFeature = all.find((f) => f.properties.id === selected) ?? null;

  // What the map shows: category toggles, build phase filter, existing on or off; the shape being edited is
  // hidden so only terra-draw's editable copy shows.
  const shown = useMemo<PlanFeatureCollection>(() => ({
    type: "FeatureCollection",
    features: all.filter((f) => {
      const p = f.properties;
      if (p.id === editing) return false;
      if (hidden.has(p.category)) return false;
      if (p.status === "existing") return showExisting;
      return phase === 0 || p.build_phase <= phase;
    }),
  }), [all, editing, hidden, showExisting, phase]);

  const toPlace = useMemo(
    () => plan.filter((p) => !p.tool && p.placed === 0).map((p) => ({ item: p, type: library?.types.find((t) => t.intervention === p.intervention_id) }))
      .filter((x): x is { item: PlanItem; type: PlanFeatureType } => !!x.type),
    [plan, library],
  );

  // ---- terra-draw ---------------------------------------------------------------------------------

  const onCreate = useRef<(geometry: PlanGeometry) => void>(() => undefined);

  useEffect(() => {
    if (!map) return;
    const white: Hex = "#ffffff";
    const black: Hex = "#000000";
    const color = () => colorRef.current;
    let draw: TerraDraw;
    try {
      draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: 7 }),
        modes: [
          new TerraDrawPointMode({ styles: { pointColor: color, pointWidth: 7, pointOutlineColor: white, pointOutlineWidth: 2 } }),
          new TerraDrawLineStringMode({
            styles: { lineStringColor: color, lineStringWidth: 3, closingPointColor: white, closingPointWidth: 4, closingPointOutlineColor: black, closingPointOutlineWidth: 1 },
          }),
          new TerraDrawPolygonMode({
            styles: {
              fillColor: color, fillOpacity: 0.35, outlineColor: white, outlineWidth: 2,
              closingPointColor: white, closingPointWidth: 5, closingPointOutlineColor: black, closingPointOutlineWidth: 2,
            },
          }),
          new TerraDrawSelectMode({
            flags: {
              point: { feature: { draggable: true } },
              linestring: { feature: { draggable: true, coordinates: { draggable: true, deletable: true, midpoints: true } } },
              polygon: { feature: { draggable: true, coordinates: { draggable: true, deletable: true, midpoints: true } } },
            },
            styles: {
              selectedPolygonColor: color, selectedPolygonFillOpacity: 0.35, selectedPolygonOutlineColor: white, selectedPolygonOutlineWidth: 2,
              selectedLineStringColor: color, selectedLineStringWidth: 3,
              selectedPointColor: color, selectedPointWidth: 8, selectedPointOutlineColor: white, selectedPointOutlineWidth: 2,
              selectionPointColor: black, selectionPointWidth: 6, selectionPointOutlineColor: white, selectionPointOutlineWidth: 2,
              midPointColor: white, midPointWidth: 3, midPointOutlineColor: black, midPointOutlineWidth: 1,
            },
          }),
        ],
      });
      draw.start();
    } catch (e) {
      setError(e instanceof Error ? `Drawing tools did not start: ${e.message}` : "Drawing tools did not start.");
      return;
    }
    drawRef.current = draw;
    draw.on("finish", (id, ctx) => {
      if (!drawTypeRef.current || ctx.mode === "select") return; // shape edits are saved with the Save shape button
      const f = draw.getSnapshotFeature(id);
      if (f) onCreate.current(f.geometry as PlanGeometry);
    });
    return () => {
      try {
        draw.stop();
      } catch {
        /* map already removed */
      }
      drawRef.current = null;
    };
  }, [map]);

  const resetDraw = useCallback(() => {
    const draw = drawRef.current;
    if (!draw) return;
    draw.setMode("static");
    draw.clear();
  }, []);

  const hasTerrain = !!summary;
  const contourActive = !!drawType && drawType.geometry === "line" && lineMode === "contour" && hasTerrain;

  const startDraw = (t: PlanFeatureType, mode: "free" | "contour" = lineMode) => {
    const draw = drawRef.current;
    if (!draw) return;
    resetDraw();
    setEditing(null);
    setSelected(null);
    setError(null);
    setContourStart(null);
    colorRef.current = (categories.get(t.category)?.color ?? "#ffffff") as Hex;
    setDrawType(t);
    if (t.geometry === "line" && mode === "contour" && hasTerrain) return; // clicks go to onContourClick
    draw.setMode(DRAW_MODE[t.geometry]);
  };

  const setLineDrawMode = (mode: "free" | "contour") => {
    setLineMode(mode);
    if (drawType) startDraw(drawType, mode);
  };

  const cancelDraw = useCallback(() => {
    resetDraw();
    setDrawType(null);
    setEditing(null);
    setContourStart(null);
  }, [resetDraw]);

  /** Along a contour: the first click starts the line, the second ends it; the line follows the contour between. */
  const onContourClick = async (lngLat: [number, number]) => {
    const t = drawTypeRef.current;
    if (!t || busy) return;
    if (!contourStart) {
      setContourStart(lngLat);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const line = await api.contourLine(projectId, contourStart, lngLat);
      const created = await api.createPlanFeature(projectId, { type: t.id, geometry: line.geometry });
      await refresh();
      if (t.intervention) announceChange("plan");
      setSelected(created.properties.id);
      setDrawType(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setContourStart(null);
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && (drawTypeRef.current || editing)) cancelDraw();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancelDraw, editing]);

  onCreate.current = async (geometry: PlanGeometry) => {
    const t = drawTypeRef.current;
    if (!t) return;
    setBusy(true);
    try {
      const created = await api.createPlanFeature(projectId, { type: t.id, geometry });
      await refresh();
      if (t.intervention) announceChange("plan");
      setSelected(created.properties.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      resetDraw();
      setDrawType(null);
      setBusy(false);
    }
  };

  const startEditShape = (f: PlanFeature) => {
    const draw = drawRef.current;
    if (!draw) return;
    resetDraw();
    setDrawType(null);
    colorRef.current = f.properties.color as Hex;
    const t = types.get(f.properties.type);
    const mode = t ? DRAW_MODE[t.geometry] : "polygon";
    const [res] = draw.addFeatures([{ type: "Feature", geometry: f.geometry, properties: { mode } } as GeoJSONStoreFeatures]);
    if (!res?.valid) {
      setError("This shape can't be edited here. Delete it and draw it again.");
      return;
    }
    setEditing(f.properties.id);
    draw.setMode("select");
    draw.selectFeature(res.id as string);
  };

  const saveShape = async () => {
    const draw = drawRef.current;
    if (!draw || !editing) return;
    const f = draw.getSnapshot().find((x) => !x.properties?.midPoint && !x.properties?.selectionPoint);
    if (!f) return cancelDraw();
    setBusy(true);
    try {
      await api.updatePlanFeature(projectId, editing, { geometry: f.geometry as PlanGeometry });
      await refresh();
      cancelDraw();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // ---- Selection and edits ---------------------------------------------------------------------------

  const onSelectFeature = useCallback((id: string | null) => {
    if (drawTypeRef.current) return;
    setSelected(id);
  }, []);

  const save = async (fid: string, body: Parameters<typeof api.updatePlanFeature>[2]) => {
    setError(null);
    const before = all.find((f) => f.properties.id === fid);
    const updated = await api.updatePlanFeature(projectId, fid, body);
    await refresh();
    if (before?.properties.intervention !== updated.properties.intervention || before?.properties.status !== updated.properties.status) {
      announceChange("plan");
    }
  };

  const remove = async (f: PlanFeature) => {
    setError(null);
    try {
      await api.deletePlanFeature(projectId, f.properties.id);
      setSelected(null);
      await refresh();
      if (f.properties.intervention) announceChange("plan");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggleCategory = (id: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useAssistantPage("design", {
    mode: "Master plan",
    features: all.length,
    by_category: Object.fromEntries((library?.categories ?? []).map((c) => [c.label, all.filter((f) => f.properties.category === c.id).length])),
    drawing: drawType?.label ?? null,
    selected_feature: selectedFeature ? `${selectedFeature.properties.type_label}: ${selectedFeature.properties.label ?? ""}` : null,
    unplaced_plan_items: toPlace.map((x) => x.item.title),
  });

  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of all) m.set(f.properties.category, (m.get(f.properties.category) ?? 0) + 1);
    return m;
  }, [all]);

  const drawHint = drawType
    ? contourActive
      ? contourStart
        ? `Now click where the ${drawType.label.toLowerCase()} should end. It follows the contour between.`
        : `Click where the ${drawType.label.toLowerCase()} should start.`
      : drawType.geometry === "point"
      ? `Click the map to place the ${drawType.label.toLowerCase()}.`
      : drawType.geometry === "line"
        ? `Click along the ${drawType.label.toLowerCase()}. Click the last point again to finish.`
        : `Click around the ${drawType.label.toLowerCase()}. Click the first point to close the shape.`
    : null;

  return (
    <div className={tv.layout}>
      <aside className={tv.left} aria-label="Feature library">
        <div className={tv.intro}>
          <p className="app-eyebrow">{project ? `${project.name} · ` : ""}{stepCount("design")}</p>
          <DesignModeSwitch projectId={projectId} mode="plan" />
          <h1 className="app-display">Draw the whole place.</h1>
          <p className="app-body">
            Place what you have and what you plan: water, gardens, trees, animals, buildings and paths. Features from
            your plan are measured and priced in the estimate.
          </p>
        </div>

        {toPlace.length > 0 && (
          <section className={`card ${tv.panel} ${styles.toPlace}`} aria-labelledby="to-place">
            <p className="app-eyebrow" id="to-place">To place, from your plan</p>
            <ul className={styles.toPlaceList}>
              {toPlace.map(({ item, type }) => (
                <li key={item.intervention_id}>
                  <button type="button" className={styles.toPlaceBtn} onClick={() => startDraw(type)} disabled={!map}
                    aria-pressed={drawType?.id === type.id}>
                    <span className={styles.swatch} style={{ background: categories.get(type.category)?.color }} aria-hidden="true" />
                    <span className={styles.toPlaceText}>
                      <span className={styles.itemTitle}>{item.title}</span>
                      <span className="app-small">Draw as {type.geometry === "polygon" ? "an area" : type.geometry === "line" ? "a line" : "a point"}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-labelledby="library-title">
          <p className="app-eyebrow" id="library-title">Feature library</p>
          {!library && !error && <p className="app-small">Loading.</p>}
          <div className={styles.library}>
            {library?.categories.map((c) => (
              <details key={c.id} className={styles.category}>
                <summary className={styles.categoryHead}>
                  <span className={styles.swatch} style={{ background: c.color }} aria-hidden="true" />
                  <span className={styles.categoryLabel}>{c.label}</span>
                  <span className="app-small">{counts.get(c.id) ?? ""}</span>
                </summary>
                <ul className={styles.typeList}>
                  {library.types.filter((t) => t.category === c.id).map((t) => (
                    <li key={t.id}>
                      <button type="button" className={styles.typeBtn} onClick={() => startDraw(t)} disabled={!map} aria-pressed={drawType?.id === t.id}>
                        <GeometryGlyph kind={t.geometry} />
                        <span>{t.label}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        </section>
      </aside>

      <div className={tv.center}>
        <div className={`${tv.mapBox} ${styles.mapWrap}`}>
          <TerrainMap
            project={project}
            summary={summary ?? null}
            data={data}
            visible={{ contours: true, flow: false, valleys: false, ridges: false, keypoints: false, hillshade: true, slope: false }}
            sectionMode={false}
            section={[]}
            onSectionClick={() => undefined}
            onStartSection={() => undefined}
            selectedKeypoint={null}
            onSelectKeypoint={() => undefined}
            showSectionTool={false}
            planFeatures={shown as FeatureCollection}
            selectedPlanFeature={selected}
            onSelectPlanFeature={drawType || editing ? null : onSelectFeature}
            onMapReady={setMap}
            mapClickActive={contourActive}
            onMapClick={contourActive ? onContourClick : undefined}
            pending={contourStart ? [contourStart] : undefined}
            planting={showPlanting ? (planting as FeatureCollection | null) : null}
            siteOverlays={site ? {
              type: "FeatureCollection",
              features: site.overlays.features.filter((f) =>
                f.properties.kind === "zone" ? site.settings.show_zones : site.settings.show_sectors),
            } : null}
          />
          {(drawType || editing) && (
            <div className={styles.drawBar} role="status" aria-live="polite">
              {drawType && (
                <>
                  {drawType.geometry === "line" && (
                    <span className={styles.modeChips}>
                      <button type="button" className="chip" aria-pressed={!contourActive} onClick={() => setLineDrawMode("free")}>Freehand</button>
                      <button type="button" className="chip" aria-pressed={contourActive} disabled={!hasTerrain}
                        title={hasTerrain ? undefined : "Needs a terrain model"} onClick={() => setLineDrawMode("contour")}>Along a contour</button>
                    </span>
                  )}
                  <span className={styles.swatch} style={{ background: categories.get(drawType.category)?.color }} aria-hidden="true" />
                  <span className="app-small">{busy ? "Saving." : drawHint}</span>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={cancelDraw}>Cancel</button>
                </>
              )}
              {editing && (
                <>
                  <span className="app-small">Drag the corners or the whole shape. Drag a midpoint to add a corner.</span>
                  <button type="button" className="btn btn-sm btn-primary" onClick={saveShape} disabled={busy}>Save shape</button>
                  <button type="button" className="btn btn-sm btn-ghost" onClick={cancelDraw}>Cancel</button>
                </>
              )}
            </div>
          )}
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        {summary === null && (
          <p className="app-small">
            No terrain model yet, so the map shows the property line only. <Link href={`/projects/${projectId}/survey`}>Add ground data</Link> to
            see contours under your plan.
          </p>
        )}
      </div>

      <aside className={tv.right} aria-label="Master plan details">
        {selectedFeature && library ? (
          <FeatureProperties
            key={selectedFeature.properties.id + selectedFeature.properties.updated_at}
            feature={selectedFeature}
            library={library}
            onSave={(body) => save(selectedFeature.properties.id, body)}
            onDelete={() => remove(selectedFeature)}
            onEditShape={() => startEditShape(selectedFeature)}
            onClose={() => setSelected(null)}
            editingShape={editing === selectedFeature.properties.id}
            planting={planting?.summary[selectedFeature.properties.id] ?? null}
            findings={checks?.findings.filter((f) => f.feature_ids.includes(selectedFeature.properties.id)) ?? []}
            hasTerrain={hasTerrain}
          />
        ) : (
          <section className={`card ${tv.panel}`} aria-labelledby="layers-title">
            <p className="app-eyebrow" id="layers-title">Layers</p>
            <ul className={styles.layerList}>
              {library?.categories.map((c) => (
                <li key={c.id}>
                  <label className={styles.layerRow}>
                    <input type="checkbox" checked={!hidden.has(c.id)} onChange={() => toggleCategory(c.id)} />
                    <span className={styles.swatch} style={{ background: c.color }} aria-hidden="true" />
                    <span className={styles.categoryLabel}>{c.label}</span>
                    <span className="app-small">{counts.get(c.id) ?? 0}</span>
                  </label>
                </li>
              ))}
            </ul>
            <fieldset className={styles.group}>
              <legend className="field-label">Build phases shown</legend>
              <div className={styles.chips}>
                {([0, 1, 2, 3] as const).map((p) => (
                  <button key={p} type="button" className="chip" aria-pressed={phase === p} onClick={() => setPhase(p)}>
                    {p === 0 ? "All" : p === 1 ? "1" : `1–${p}`}
                  </button>
                ))}
              </div>
            </fieldset>
            <label className={styles.check}>
              <input type="checkbox" checked={showExisting} onChange={(e) => setShowExisting(e.target.checked)} />
              <span className="app-small">Show existing features</span>
            </label>
            <label className={styles.check}>
              <input type="checkbox" checked={showPlanting} onChange={(e) => setShowPlanting(e.target.checked)} />
              <span className="app-small">Show plant positions (zoom in)</span>
            </label>
          </section>
        )}

        {!selectedFeature && site && <SitePanel key={site.center_source ?? "none"} projectId={projectId} site={site} onChange={setSite} />}
        {!selectedFeature && <ChecksPanel checks={checks} onSelect={(id) => setSelected(id)} />}

        {!selectedFeature && (
          <section className={`card ${tv.panel}`} aria-labelledby="features-title">
            <p className="app-eyebrow" id="features-title">Features</p>
            {all.length === 0 && <p className="app-small">Nothing placed yet. Pick a feature from the library, then draw it on the map.</p>}
            <ul className={styles.featureList}>
              {all.map((f) => (
                <li key={f.properties.id} className={styles.featureRow}>
                  <button type="button" className={styles.featureMain} onClick={() => setSelected(f.properties.id)}>
                    <span className={styles.swatch} style={{ background: f.properties.color }} aria-hidden="true" />
                    <span className={styles.featureText}>
                      <span className={styles.itemTitle}>{f.properties.label || f.properties.type_label}</span>
                      <span className="app-small">
                        {measure(f)}
                        {f.properties.status === "existing" ? " · existing" : ` · phase ${f.properties.build_phase}`}
                      </span>
                    </span>
                  </button>
                  <button type="button" className="icon-btn" aria-label={`Delete ${f.properties.label || f.properties.type_label}`} onClick={() => remove(f)}>
                    <IconX size={16} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className={tv.next}>
          <Link href={`/projects/${projectId}/sheet`} className="btn">
            Master plan sheet <IconArrowRight />
          </Link>
          <Link href={`/projects/${projectId}/scene`} className="btn">
            3D view and fly-through <IconArrowRight />
          </Link>
          <Link href={`/projects/${projectId}/estimate`} className="btn btn-primary">
            Review estimate <IconArrowRight />
          </Link>
          <p className="app-small">Areas, lengths and plant counts are measured from what you draw.</p>
        </div>
      </aside>
    </div>
  );
}

function measure(f: PlanFeature): string {
  const p = f.properties;
  if (p.area_m2 != null) return formatArea(p.area_m2);
  if (p.length_m != null) return formatLength(p.length_m);
  return p.label && p.label !== p.type_label ? p.type_label : "Point";
}

function GeometryGlyph({ kind }: { kind: "point" | "line" | "polygon" }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className={styles.glyph}>
      {kind === "point" && <circle cx="8" cy="8" r="3.5" fill="currentColor" />}
      {kind === "line" && <path d="M2 12 C6 4, 10 12, 14 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />}
      {kind === "polygon" && <path d="M3 4 L12 2.5 L13.5 12 L4 13.5 Z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />}
    </svg>
  );
}

