"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { FeatureCollection, Point } from "geojson";
import {
  api,
  type DesignCollection,
  type DesignFeature,
  type Estimate,
  type KeypointProps,
  type LayerName,
  type Profile,
  type Project,
  type Proposal,
  type TerrainSummary,
} from "@/lib/api";
import { formatFeet, ftToM, m2ToAcres, mToFt } from "@/lib/units";
import { IconAlert, IconArrowRight, IconX } from "../Icons";
import type { LayerData } from "../terrain/TerrainMap";
import { SectionProfile } from "../terrain/SectionProfile";
import tv from "../terrain/TerrainView.module.css";
import { useAssistantDesign, useAssistantPage } from "@/lib/assistant";
import styles from "./DesignView.module.css";

const TerrainMap = dynamic(() => import("../terrain/TerrainMap").then((m) => m.TerrainMap), {
  ssr: false,
  loading: () => <div className={tv.mapLoading} aria-hidden="true" />,
});

const GRADES = [200, 300, 400, 500];
type Mode = "keyline" | "swale";

const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");
const usd = (n: number) => `$${fmtInt(n)}`;

export function DesignView({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<TerrainSummary | null>(null);
  const [data, setData] = useState<LayerData>({});
  const [design, setDesign] = useState<DesignCollection | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [mode, setMode] = useState<Mode>("keyline");
  const [keypoint, setKeypoint] = useState<string>("");
  const [gradeDen, setGradeDen] = useState(300);
  const [spacingFt, setSpacingFt] = useState("16");
  const [extent, setExtent] = useState<"site" | "valley">("valley");
  const [pattern, setPattern] = useState<"parallel" | "graded">("parallel");
  const [allowDraft, setAllowDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  const [widthFt, setWidthFt] = useState("6");
  const [depthFt, setDepthFt] = useState("1.5");
  const [berm, setBerm] = useState(true);
  const [placing, setPlacing] = useState(false);
  const [pending, setPending] = useState<[number, number][]>([]);

  const [selected, setSelected] = useState<string | null>(null);
  const [previewProposal, setPreviewProposal] = useState<Proposal | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const refreshDesign = useCallback(async () => {
    const [d, e] = await Promise.all([api.getDesign(projectId), api.getEstimate(projectId).catch(() => null)]);
    setDesign(d);
    setEstimate(e);
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setLoadError(e.message));
    (async () => {
      try {
        const s = await api.getTerrain(projectId);
        setSummary(s);
        if (!s) return;
        // Keypoints and the design first; contours are the heaviest layer, so they arrive on their own.
        const names: LayerName[] = ["keypoints", "valleys", "ridges", "flow", "contours"];
        names.forEach((n) =>
          api.getLayer(projectId, n).then((fc) => setData((d) => ({ ...d, [n]: fc as FeatureCollection }))).catch(() => undefined),
        );
        await refreshDesign();
      } catch (e) {
        setLoadError((e as Error).message);
      }
    })();
  }, [projectId, refreshDesign]);

  const keypoints = useMemo(
    () =>
      ((data.keypoints as FeatureCollection<Point, KeypointProps> | undefined)?.features ?? [])
        .slice()
        .sort((a, b) => a.properties.id.localeCompare(b.properties.id, undefined, { numeric: true })),
    [data.keypoints],
  );
  useEffect(() => {
    if (!keypoint && keypoints.length) {
      setKeypoint((keypoints.find((k) => k.properties.confirmed) ?? keypoints[0]).properties.id);
    }
  }, [keypoints, keypoint]);

  const designGrade = (summary?.quality.design_pct ?? 0) >= 50;
  const tooCoarse = !designGrade && (summary?.quality.coarse_pct ?? 0) >= 50;
  const needsDraft = !designGrade && !tooCoarse;
  const canGenerate = !!keypoint && !busy && !tooCoarse && (designGrade || allowDraft);

  const features = design?.features ?? [];
  const keylines = features.filter((f) => f.properties.kind === "keyline");
  const swales = features.filter((f) => f.properties.kind === "swale");
  const rips = features.filter((f) => f.properties.kind === "rip");
  const selectedFeature = features.find((f) => f.properties.id === selected) ?? null;

  useAssistantDesign(
    summary && !tooCoarse ? { allowPlanning: needsDraft, onPreview: setPreviewProposal, onDesignChanged: refreshDesign } : null,
  );
  useAssistantPage("design", {
    terrain_model: summary ? "built" : "missing",
    terrain_grade: !summary ? null : designGrade ? "design" : tooCoarse ? "coarse" : "planning",
    mode: mode === "keyline" ? "Keyline pattern" : "Swale on contour",
    keyline_settings: mode === "keyline"
      ? { keypoint, grade_off_contour: `1:${gradeDen}`, rip_spacing_ft: spacingFt, extent, pattern }
      : undefined,
    swale_settings: mode === "swale" ? { width_ft: widthFt, depth_ft: depthFt, berm, placing } : undefined,
    planning_draft_ticked: needsDraft ? allowDraft : undefined,
    keypoints: keypoints.map((k) => ({ id: k.properties.id, confirmed: k.properties.confirmed })),
    saved_design: { keylines: keylines.length, rip_lines: rips.length, swales: swales.length },
    selected_element: selectedFeature ? `${selectedFeature.properties.kind} ${selectedFeature.properties.label ?? ""}`.trim() : null,
    previewing_proposal: previewProposal ? previewProposal.kind : null,
    estimate_total_usd: estimate ? [Math.round(estimate.total_low), Math.round(estimate.total_high)] : null,
  });

  const generate = async () => {
    setBusy(true);
    setActionError(null);
    setNotes([]);
    try {
      const spacing = ftToM(parseFloat(spacingFt));
      if (!(spacing > 0)) throw new Error("Enter a rip spacing in feet.");
      const res = await api.createKeyline(projectId, {
        keypoint_id: keypoint,
        grade: 1 / gradeDen,
        spacing_m: Math.round(spacing * 100) / 100,
        extent,
        pattern,
        allow_planning: needsDraft && allowDraft,
      });
      setNotes(res.notes);
      setSelected(res.keyline.properties.id);
      await refreshDesign();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onMapClick = useCallback(
    async (c: [number, number]) => {
      if (!placing) return;
      const pts = [...pending, c];
      setPending(pts);
      if (pts.length < 2) return;
      setPlacing(false);
      setBusy(true);
      setActionError(null);
      try {
        const f = await api.createSwale(projectId, {
          start: pts[0],
          end: pts[1],
          width_m: ftToM(parseFloat(widthFt)),
          depth_m: ftToM(parseFloat(depthFt)),
          berm,
          allow_planning: needsDraft && allowDraft,
        });
        setSelected(f.properties.id);
        await refreshDesign();
      } catch (e) {
        setActionError((e as Error).message);
      } finally {
        setPending([]);
        setBusy(false);
      }
    },
    [placing, pending, projectId, widthFt, depthFt, berm, needsDraft, allowDraft, refreshDesign],
  );

  const remove = async (f: DesignFeature) => {
    setActionError(null);
    try {
      await api.deleteElement(projectId, f.properties.id);
      if (selected === f.properties.id) setSelected(null);
      await refreshDesign();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  // Profile of the selected line.
  useEffect(() => {
    setProfile(null);
    setProfileError(null);
    if (!selected) return;
    setProfileLoading(true);
    api
      .elementProfile(projectId, selected)
      .then(setProfile)
      .catch((e: Error) => setProfileError(e.message))
      .finally(() => setProfileLoading(false));
  }, [projectId, selected]);

  const q = estimate?.quantities;
  const profileTitle = selectedFeature
    ? selectedFeature.properties.kind === "swale"
      ? `${selectedFeature.properties.label}: dead level at ${formatFeet(selectedFeature.properties.elevation_m, 1)} ft.`
      : `${selectedFeature.properties.label}: ${formatFeet(selectedFeature.properties.length_m)} ft along the line.`
    : undefined;

  return (
    <div className={tv.layout}>
      <aside className={tv.left} aria-label="Design tools">
        <div className={tv.intro}>
          <p className="app-eyebrow">{project ? `${project.name} · ` : ""}Step 4 of 5</p>
          <h1 className="app-display">Lay the lines that hold the water.</h1>
          <p className="app-body">
            The engine draws each keyline through a keypoint, falling gently toward the ridges, then repeats it across the
            slope. Swales follow a contour dead level.
          </p>
        </div>

        <div className={styles.tabs} role="tablist" aria-label="Element">
          {(["keyline", "swale"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              className="chip"
              aria-pressed={mode === m}
              onClick={() => {
                setMode(m);
                setPlacing(false);
                setPending([]);
              }}
            >
              {m === "keyline" ? "Keyline pattern" : "Swale on contour"}
            </button>
          ))}
        </div>

        {needsDraft && (
          <label className={styles.draft}>
            <input type="checkbox" checked={allowDraft} onChange={(e) => setAllowDraft(e.target.checked)} />
            <span>
              <span className="app-title">Draft on planning-grade terrain</span>
              <span className="app-small">Lines may sit a metre or more off in the field. Exports are marked draft.</span>
            </span>
          </label>
        )}

        {mode === "keyline" ? (
          <div className={styles.form}>
            <fieldset className={styles.group}>
              <legend className="field-label">Keypoint</legend>
              {data.keypoints && keypoints.length === 0 && <p className="app-small">No keypoints on this site.</p>}
              {!data.keypoints && <p className="app-small">Loading keypoints.</p>}
              <div className={styles.chips}>
                {keypoints.map((k) => (
                  <button
                    key={k.properties.id}
                    type="button"
                    className="chip"
                    aria-pressed={keypoint === k.properties.id}
                    onClick={() => setKeypoint(k.properties.id)}
                    title={`${formatFeet(k.properties.elevation_m)} ft${k.properties.confirmed ? ", confirmed" : ""}`}
                  >
                    {k.properties.id}
                    {k.properties.confirmed ? "" : " ·"}
                  </button>
                ))}
              </div>
              {keypoints.some((k) => !k.properties.confirmed) && (
                <p className="app-small">A dot marks a keypoint not yet confirmed on the terrain step.</p>
              )}
            </fieldset>

            <fieldset className={styles.group}>
              <legend className="field-label">Grade off contour</legend>
              <div className={styles.chips}>
                {GRADES.map((g) => (
                  <button key={g} type="button" className="chip" aria-pressed={gradeDen === g} onClick={() => setGradeDen(g)}>
                    1:{g}
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="field">
              <label className="field-label" htmlFor="spacing">Rip spacing (ft)</label>
              <input id="spacing" className="input" inputMode="decimal" value={spacingFt} onChange={(e) => setSpacingFt(e.target.value)} />
            </div>

            <fieldset className={styles.group}>
              <legend className="field-label">Extent</legend>
              <div className={styles.chips}>
                <button type="button" className="chip" aria-pressed={extent === "valley"} onClick={() => setExtent("valley")}>Keypoint valley</button>
                <button type="button" className="chip" aria-pressed={extent === "site"} onClick={() => setExtent("site")}>Whole site</button>
              </div>
            </fieldset>

            <fieldset className={styles.group}>
              <legend className="field-label">Pattern</legend>
              <div className={styles.chips}>
                <button type="button" className="chip" aria-pressed={pattern === "parallel"} onClick={() => setPattern("parallel")}>Parallel to keyline</button>
                <button type="button" className="chip" aria-pressed={pattern === "graded"} onClick={() => setPattern("graded")}>Each line graded</button>
              </div>
              <p className="app-small">
                {pattern === "parallel"
                  ? "Yeomans' pattern: even spacing for the plow; grade drifts away from the keyline."
                  : "Every line holds the grade; spacing varies with the land."}
              </p>
            </fieldset>

            <button type="button" className="btn btn-primary" onClick={generate} disabled={!canGenerate}>
              {busy ? "Computing." : keylines.some((k) => k.properties.keypoint_id === keypoint) ? "Regenerate pattern" : "Generate pattern"}
            </button>
          </div>
        ) : (
          <div className={styles.form}>
            <div className={styles.row2}>
              <div className="field">
                <label className="field-label" htmlFor="sw-w">Width (ft)</label>
                <input id="sw-w" className="input" inputMode="decimal" value={widthFt} onChange={(e) => setWidthFt(e.target.value)} />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="sw-d">Depth (ft)</label>
                <input id="sw-d" className="input" inputMode="decimal" value={depthFt} onChange={(e) => setDepthFt(e.target.value)} />
              </div>
            </div>
            <label className={styles.check}>
              <input type="checkbox" checked={berm} onChange={(e) => setBerm(e.target.checked)} />
              <span className="app-small">Berm on the downhill side</span>
            </label>
            {placing ? (
              <>
                <p className="app-body" aria-live="polite">
                  {pending.length === 0 ? "Click the start of the swale on the map." : "Click where the swale should end."}
                </p>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => { setPlacing(false); setPending([]); }}>
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy || tooCoarse || (needsDraft && !allowDraft)}
                onClick={() => { setPlacing(true); setPending([]); setSelected(null); }}
              >
                {busy ? "Computing." : "Place swale"}
              </button>
            )}
            <p className="app-small">The swale follows the contour through the start point. Storage is width × depth × length.</p>
          </div>
        )}

        {actionError && <p className="error-text" role="alert">{actionError}</p>}
      </aside>

      <div className={tv.center}>
        <div className={tv.mapBox}>
          <TerrainMap
            project={project}
            summary={summary}
            data={data}
            visible={{ contours: true, flow: false, valleys: true, ridges: true, keypoints: true, hillshade: true, slope: false }}
            sectionMode={false}
            section={[]}
            onSectionClick={() => undefined}
            onStartSection={() => undefined}
            selectedKeypoint={keypoint}
            onSelectKeypoint={(id) => { setKeypoint(id); setMode("keyline"); }}
            design={design}
            selectedElement={selected}
            onSelectElement={setSelected}
            mapClickActive={placing}
            onMapClick={onMapClick}
            pending={pending}
            preview={previewProposal?.preview ?? null}
            showSectionTool={false}
          />
        </div>
        <SectionProfile
          profile={profile}
          loading={profileLoading}
          error={profileError}
          sectionMode={false}
          onStart={() => undefined}
          onClear={() => setSelected(null)}
          eyebrow="Line profile"
          title={profileTitle ?? "Pick a line on the map."}
          emptyText="Select a keyline, rip line or swale on the map to see the ground along it."
          showDraw={false}
        />
      </div>

      <aside className={tv.right} aria-label="Design summary">
        {loadError && <p className="error-text" role="alert">{loadError}</p>}
        {summary === null && !loadError && (
          <section className={`card ${tv.panel}`}>
            <p className="app-eyebrow">No terrain model yet</p>
            <h2 className="app-h2">Build the terrain first.</h2>
            <Link href={`/projects/${projectId}/survey`} className="btn btn-sm">Go to survey</Link>
          </section>
        )}
        {summary && !designGrade && (
          <section className={`card ${tv.panel} ${styles.gradeCard}`}>
            <p className="app-eyebrow"><IconAlert size={14} /> {tooCoarse ? "Coarse terrain" : "Planning-grade terrain"}</p>
            <p className="app-body">
              {tooCoarse
                ? "The terrain model is too coarse for keylines. Add a drone or RTK survey."
                : "Keylines need design-grade ground data. Add a drone or RTK survey, or draw a draft here to plan with."}
            </p>
          </section>
        )}

        <section className={`card ${tv.panel}`} aria-labelledby="totals">
          <p className="app-eyebrow" id="totals">Pattern</p>
          <dl className={tv.stats}>
            <div className={tv.statWide}>
              <dt className="field-label">Total rip line</dt>
              <dd>
                <span className="app-numeral">{q ? fmtInt(q.rip_length_ft) : "0"}</span> <span className="app-small">ft</span>
              </dd>
            </div>
            <div>
              <dt className="field-label">Lines</dt>
              <dd><span className={tv.num}>{rips.length + keylines.length}</span></dd>
            </div>
            <div>
              <dt className="field-label">Area treated</dt>
              <dd><span className={tv.num}>{q ? q.treated_acres.toFixed(1) : "0"}</span> <span className="app-small">ac</span></dd>
            </div>
            {estimate && estimate.lines.length > 0 && (
              <div className={tv.statWide}>
                <dt className="field-label">Build estimate</dt>
                <dd className="app-small">{usd(estimate.total_low)} – {usd(estimate.total_high)}</dd>
              </div>
            )}
          </dl>
          {notes.length > 0 && (
            <ul className={styles.notes}>
              {notes.map((n) => <li key={n} className="app-small">{n}</li>)}
            </ul>
          )}
        </section>

        <section className={`card ${tv.panel}`} aria-labelledby="elements">
          <p className="app-eyebrow" id="elements">Design elements</p>
          {features.length === 0 && <p className="app-small">Nothing yet. Generate a keyline pattern or place a swale.</p>}
          <ul className={styles.elements}>
            {keylines.map((k) => {
              const n = rips.filter((r) => r.properties.group_id === k.properties.group_id).length;
              return (
                <ElementRow key={k.properties.id} f={k} selected={selected === k.properties.id} onSelect={setSelected} onDelete={remove}
                  detail={`${formatFeet(k.properties.length_m)} ft · ${n} rip lines${k.properties.draft ? " · draft" : ""}`} />
              );
            })}
            {swales.map((s) => (
              <ElementRow key={s.properties.id} f={s} selected={selected === s.properties.id} onSelect={setSelected} onDelete={remove}
                detail={`${formatFeet(s.properties.length_m)} ft · ${fmtInt(s.properties.storage_gal ?? 0)} gal`} />
            ))}
          </ul>
        </section>

        {selectedFeature && <ElementDetail f={selectedFeature} />}

        <div className={tv.next}>
          <Link href={`/projects/${projectId}/estimate`} className={`btn btn-primary ${features.length ? "" : styles.disabledLink}`} aria-disabled={!features.length}>
            Review estimate <IconArrowRight />
          </Link>
          <p className="app-small">Lines are computed from the terrain model, never drawn by hand.</p>
        </div>
      </aside>
    </div>
  );
}

function ElementRow({ f, selected, onSelect, onDelete, detail }: {
  f: DesignFeature;
  selected: boolean;
  onSelect: (id: string) => void;
  onDelete: (f: DesignFeature) => void;
  detail: string;
}) {
  return (
    <li className={`${styles.element} ${selected ? styles.elementSelected : ""}`}>
      <button type="button" className={styles.elementMain} onClick={() => onSelect(f.properties.id)} aria-pressed={selected}>
        <span className={styles.elementLabel}>{f.properties.label}</span>
        <span className="app-small">{detail}</span>
      </button>
      <button type="button" className="icon-btn" aria-label={`Delete ${f.properties.label}`} onClick={() => onDelete(f)}>
        <IconX size={16} />
      </button>
    </li>
  );
}

function ElementDetail({ f }: { f: DesignFeature }) {
  const p = f.properties;
  const rows: [string, string][] = [["Length", `${formatFeet(p.length_m)} ft`]];
  if (p.kind === "swale") {
    rows.push(["Elevation", `${formatFeet(p.elevation_m, 1)} ft`]);
    rows.push(["Width × depth", `${mToFt(p.width_m ?? 0).toFixed(1)} × ${mToFt(p.depth_m ?? 0).toFixed(1)} ft`]);
    rows.push(["Cut", `${fmtInt((p.cut_volume_m3 ?? 0) * 1.30795)} cu yd`]);
    rows.push(["Storage", `${fmtInt(p.storage_gal ?? 0)} gal`]);
    rows.push(["Catchment", `${m2ToAcres(p.catchment_m2 ?? 0).toFixed(1)} ac`]);
    rows.push(["Steepest ground", `${Math.round(p.terrain_slope_max_pct ?? 0)}%`]);
  } else {
    if (p.fall_to_ridges_min != null) {
      rows.push(["Fall toward ridges", p.fall_to_ridges_min > 0 ? `1:${fmtInt(1 / p.fall_to_ridges_min)}` : "toward the valley"]);
    }
    if (p.steepest_grade) rows.push(["Steepest stretch", `1:${fmtInt(1 / p.steepest_grade)}`]);
    if (p.pass) rows.push(["Pass", String(p.pass)]);
  }
  return (
    <section className={`card ${styles.detail}`} aria-label={`${p.label} details`}>
      <p className="app-eyebrow">{p.kind === "swale" ? "Swale" : p.kind === "keyline" ? "Keyline" : "Rip line"} {p.label}</p>
      <dl className={styles.detailList}>
        {rows.map(([k, v]) => (
          <div key={k}><dt className="app-small">{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      {p.draft && <p className="app-small">Draft on planning-grade terrain.</p>}
      {p.notes?.map((n) => <p key={n} className={`app-small ${styles.note}`}><IconAlert size={12} /> {n}</p>)}
    </section>
  );
}

