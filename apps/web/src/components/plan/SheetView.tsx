"use client";
// Master plan sheet: in-app tools for the printable plan. Settings save as they change; the preview is the server's
// SVG (the same drawing the PDF is made from), and labels can be dragged on it to new spots.
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { api, exportUrl, type PlanLibrary, type PlanSheetSettings, type Project } from "@/lib/api";
import { IconArrowLeft, IconDownload } from "../Icons";
import styles from "./Sheet.module.css";

const BASES = [["aerial", "Aerial photo"], ["terrain", "Terrain shading"], ["plain", "Plain"]] as const;
const LABELS = [["callouts", "Callouts"], ["on_features", "On features"], ["off", "Off"]] as const;

interface Drag {
  g: SVGGElement;
  key: string;
  start: DOMPoint;
  box: DOMRect;
  baseline: number;
  moved: boolean;
}

export function SheetView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [library, setLibrary] = useState<PlanLibrary | null>(null);
  const [settings, setSettings] = useState<PlanSheetSettings | null>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [baseUsed, setBaseUsed] = useState<PlanSheetSettings["base"] | null>(null);
  const [labelKeys, setLabelKeys] = useState<string[]>([]);
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previewRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seq = useRef(0);

  const refreshSvg = useCallback(async () => {
    const mine = ++seq.current;
    setUpdating(true);
    try {
      const { svg: text, base } = await api.getPlanSheetSvg(projectId);
      if (mine !== seq.current) return; // a newer render is on its way
      setSvg(text);
      setBaseUsed(base);
      setError(null);
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setUpdating(false);
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setError(e.message));
    api.getPlanLibrary().then(setLibrary).catch(() => undefined);
    api.getPlanSheet(projectId).then(setSettings).catch((e: Error) => setError(e.message));
    refreshSvg();
  }, [projectId, refreshSvg]);

  // Labels drawn on the sheet, for the show/hide list (hidden ones aren't drawn, so keep those from the settings).
  useEffect(() => {
    if (!svg) return;
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    const drawn = Array.from(doc.querySelectorAll("g.lbl")).map((g) => g.getAttribute("data-key") ?? "").filter(Boolean);
    setLabelKeys(Array.from(new Set([...drawn, ...(settings?.hidden_labels ?? [])])).sort());
  }, [svg, settings?.hidden_labels]);

  /** Change settings now, save after a pause, then redraw. */
  const update = (patch: Partial<PlanSheetSettings>, delay = 350) => {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        setSettings(await api.putPlanSheet(projectId, next));
        await refreshSvg();
      } catch (e) {
        setError((e as Error).message);
      }
    }, delay);
  };

  // ---- Dragging labels on the preview --------------------------------------------------------------

  const svgPoint = (e: { clientX: number; clientY: number }) => {
    const el = previewRef.current?.querySelector("svg");
    if (!el) return null;
    const pt = el.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = el.getScreenCTM();
    return ctm ? pt.matrixTransform(ctm.inverse()) : null;
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (settings?.labels === "off") return;
    const g = (e.target as Element).closest("g.lbl") as SVGGElement | null;
    const start = g && svgPoint(e);
    if (!g || !start) return;
    e.preventDefault();
    previewRef.current?.setPointerCapture(e.pointerId);
    dragRef.current = { g, key: g.dataset.key ?? "", start, box: g.getBBox(), baseline: Number(g.dataset.y), moved: false };
    g.classList.add(styles.dragging);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    const p = d && svgPoint(e);
    if (!d || !p) return;
    const dx = p.x - d.start.x;
    const dy = p.y - d.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
    d.g.setAttribute("transform", `translate(${dx} ${dy})`);
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    d.g.classList.remove(styles.dragging);
    const p = svgPoint(e);
    const el = previewRef.current?.querySelector("svg");
    if (!d.moved || !p || !el || !settings) {
      d.g.removeAttribute("transform");
      return;
    }
    const vb = el.viewBox.baseVal;
    // Saved as the label's left edge and first baseline, as fractions of the sheet.
    const x = (d.box.x + p.x - d.start.x) / vb.width;
    const y = (d.baseline + p.y - d.start.y) / vb.height;
    const clamp = (v: number) => Math.min(0.995, Math.max(0.005, v));
    update({ label_positions: { ...settings.label_positions, [d.key]: [clamp(x), clamp(y)] } }, 0);
  };

  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const moved = settings ? Object.keys(settings.label_positions).length : 0;

  return (
    <div className={styles.layout}>
      <aside className={styles.controls} aria-label="Sheet settings">
        <div className={styles.intro}>
          <Link href={`/projects/${projectId}/design?mode=plan`} className={`app-small ${styles.back}`}>
            <IconArrowLeft size={14} /> Master plan
          </Link>
          <p className="app-eyebrow">{project ? `${project.name} · ` : ""}Master plan sheet</p>
          <h1 className="app-display">Print the plan.</h1>
          <p className="app-body">Set up the sheet, drag labels where they read best, and download a PDF to print or share.</p>
        </div>

        {settings && (
          <>
            <a className="btn btn-primary" href={exportUrl.masterPlanPdf(projectId)} download>
              <IconDownload size={16} /> Download PDF
            </a>

            <fieldset className={styles.group}>
              <legend className="field-label">Sheet size</legend>
              <div className={styles.chips}>
                {(["11x17", "24x36"] as const).map((v) => (
                  <button key={v} type="button" className="chip" aria-pressed={settings.size === v} onClick={() => update({ size: v }, 0)}>
                    {v.replace("x", " × ")} in
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="field">
              <label className="field-label" htmlFor="sh-title">Title</label>
              <input id="sh-title" className="input" maxLength={60} value={settings.title} onChange={(e) => update({ title: e.target.value }, 700)} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="sh-sub">Address line</label>
              <input id="sh-sub" className="input" maxLength={120} placeholder={project?.address ?? ""} value={settings.subtitle ?? ""}
                onChange={(e) => update({ subtitle: e.target.value || null }, 700)} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="sh-by">Prepared by</label>
              <input id="sh-by" className="input" maxLength={80} value={settings.prepared_by} onChange={(e) => update({ prepared_by: e.target.value }, 700)} />
            </div>

            <fieldset className={styles.group}>
              <legend className="field-label">Base map</legend>
              <div className={styles.chips}>
                {BASES.map(([v, label]) => (
                  <button key={v} type="button" className="chip" aria-pressed={settings.base === v} onClick={() => update({ base: v }, 0)}>{label}</button>
                ))}
              </div>
              {baseUsed && baseUsed !== settings.base && !updating && (
                <p className="app-small" role="status">
                  {settings.base === "aerial" ? "The aerial photo couldn't be loaded" : "This project has no terrain model yet"}
                  {baseUsed === "terrain" ? ", so the sheet shows terrain shading." : ", so the sheet uses a plain background."}
                </p>
              )}
              <label className={styles.check}>
                <input type="checkbox" checked={settings.contours} onChange={(e) => update({ contours: e.target.checked }, 0)} />
                <span className="app-small">Contours</span>
              </label>
            </fieldset>

            <fieldset className={styles.group}>
              <legend className="field-label">Labels</legend>
              <div className={styles.chips}>
                {LABELS.map(([v, label]) => (
                  <button key={v} type="button" className="chip" aria-pressed={settings.labels === v} onClick={() => update({ labels: v }, 0)}>{label}</button>
                ))}
              </div>
              {settings.labels !== "off" && (
                <p className="app-small">Drag a label on the sheet to move it.{" "}
                  {moved > 0 && (
                    <button type="button" className={styles.linkBtn} onClick={() => update({ label_positions: {} }, 0)}>
                      Reset {moved} moved label{moved === 1 ? "" : "s"}
                    </button>
                  )}
                </p>
              )}
              {settings.labels !== "off" && labelKeys.length > 0 && (
                <ul className={styles.labelList}>
                  {labelKeys.map((key) => (
                    <li key={key}>
                      <label className={styles.check}>
                        <input type="checkbox" checked={!settings.hidden_labels.includes(key)}
                          onChange={() => update({ hidden_labels: toggle(settings.hidden_labels, key) }, 0)} />
                        <span className="app-small">{key.charAt(0) + key.slice(1).toLowerCase()}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>

            <fieldset className={styles.group}>
              <legend className="field-label">Build phases shown</legend>
              <div className={styles.chips}>
                {([0, 1, 2, 3] as const).map((p) => (
                  <button key={p} type="button" className="chip" aria-pressed={settings.phases === p} onClick={() => update({ phases: p }, 0)}>
                    {p === 0 ? "All" : p === 1 ? "1" : `1–${p}`}
                  </button>
                ))}
              </div>
              <label className={styles.check}>
                <input type="checkbox" checked={settings.show_existing} onChange={(e) => update({ show_existing: e.target.checked }, 0)} />
                <span className="app-small">Existing features</span>
              </label>
            </fieldset>

            {library && (
              <fieldset className={styles.group}>
                <legend className="field-label">Categories</legend>
                <ul className={styles.labelList}>
                  {library.categories.map((c) => (
                    <li key={c.id}>
                      <label className={styles.check}>
                        <input type="checkbox" checked={!settings.hidden_categories.includes(c.id)}
                          onChange={() => update({ hidden_categories: toggle(settings.hidden_categories, c.id) }, 0)} />
                        <span className={styles.swatch} style={{ background: c.color }} aria-hidden="true" />
                        <span className="app-small">{c.label}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              </fieldset>
            )}

            <label className={styles.check}>
              <input type="checkbox" checked={settings.schedule} onChange={(e) => update({ schedule: e.target.checked }, 0)} />
              <span className="app-small">Plant schedule</span>
            </label>

            <div className="field">
              <label className="field-label" htmlFor="sh-notes">Notes on the sheet</label>
              <textarea id="sh-notes" className={`input ${styles.notes}`} rows={4} maxLength={800} value={settings.notes}
                onChange={(e) => update({ notes: e.target.value }, 900)} />
            </div>
          </>
        )}
      </aside>

      <section className={styles.previewCol} aria-label="Sheet preview">
        <div className={styles.previewBar}>
          <span className="app-small" role="status" aria-live="polite">{updating ? "Updating the sheet." : svg ? "Preview" : "Drawing the sheet."}</span>
          {error && <span className="error-text" role="alert">{error}</span>}
        </div>
        <div
          ref={previewRef}
          className={`${styles.paper} ${updating ? styles.stale : ""} ${settings?.labels !== "off" ? styles.draggable : ""}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          // The SVG comes from our own API; user text in it is escaped by the server renderer.
          dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
        />
      </section>
    </div>
  );
}
