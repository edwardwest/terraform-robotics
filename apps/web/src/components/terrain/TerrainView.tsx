"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import type { FeatureCollection, Point } from "geojson";
import {
  api,
  jobStore,
  type KeypointProps,
  type LayerName,
  type Profile,
  type Project,
  type TerrainSummary,
} from "@/lib/api";
import { jobProgress, useJobPolling } from "@/lib/useJob";
import { formatAcres, formatFeet, formatPct, formatResolution } from "@/lib/units";
import { IconAlert, IconArrowRight, IconCheck } from "../Icons";
import type { LayerData } from "./TerrainMap";
import type { ToggleKey } from "./layers";
import { SectionProfile } from "./SectionProfile";
import { useAssistantPage } from "@/lib/assistant";
import styles from "./TerrainView.module.css";

const TerrainMap = dynamic(() => import("./TerrainMap").then((m) => m.TerrainMap), {
  ssr: false,
  loading: () => <div className={styles.mapLoading} aria-hidden="true" />,
});

const LAYER_TOGGLES: { key: ToggleKey; label: string; swatch: string }[] = [
  { key: "contours", label: "Contours", swatch: "contours" },
  { key: "flow", label: "Flow paths", swatch: "flow" },
  { key: "valleys", label: "Valleys", swatch: "valleys" },
  { key: "ridges", label: "Ridges", swatch: "ridges" },
  { key: "keypoints", label: "Keypoints", swatch: "keypoints" },
  { key: "hillshade", label: "Hillshade", swatch: "hillshade" },
  { key: "slope", label: "Slope", swatch: "slope" },
];

const DIRECTION_WORDS: Record<string, string> = {
  N: "north", NE: "northeast", E: "east", SE: "southeast", S: "south", SW: "southwest", W: "west", NW: "northwest",
};

export function TerrainView({ projectId }: { projectId: string }) {
  return (
    <Suspense fallback={null}>
      <TerrainViewInner projectId={projectId} />
    </Suspense>
  );
}

function TerrainViewInner({ projectId }: { projectId: string }) {
  const search = useSearchParams();
  const [jobId, setJobId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [summary, setSummary] = useState<TerrainSummary | null>(null);
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [data, setData] = useState<LayerData>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<ToggleKey, boolean>>({
    contours: true, flow: true, valleys: true, ridges: true, keypoints: true, hillshade: true, slope: false,
  });
  const [sectionMode, setSectionMode] = useState(false);
  const [section, setSection] = useState<[number, number][]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [selectedKp, setSelectedKp] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [kpError, setKpError] = useState<string | null>(null);

  useEffect(() => {
    setJobId(search.get("job") || jobStore.get(projectId));
  }, [search, projectId]);

  const { job, error: jobPollError } = useJobPolling(jobId);
  const running = job && (job.status === "queued" || job.status === "running");

  const loadTerrain = useCallback(async () => {
    try {
      const s = await api.getTerrain(projectId);
      setSummary(s);
      setSummaryLoaded(true);
      if (!s) return;
      const names: LayerName[] = s.layers?.length ? s.layers : ["contours", "flow", "valleys", "ridges", "keypoints"];
      const results = await Promise.allSettled(names.map((n) => api.getLayer(projectId, n)));
      const next: LayerData = {};
      results.forEach((r, i) => {
        if (r.status === "fulfilled") next[names[i]] = r.value as FeatureCollection;
      });
      setData(next);
      const failed = results.filter((r) => r.status === "rejected").length;
      if (failed) setLoadError(`${failed} of ${names.length} layers did not load.`);
    } catch (e) {
      setSummaryLoaded(true);
      setLoadError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setLoadError(e.message));
    loadTerrain();
  }, [projectId, loadTerrain]);

  // Reload when the job finishes.
  useEffect(() => {
    if (job?.status === "succeeded") {
      jobStore.clear(projectId);
      loadTerrain();
    }
  }, [job?.status, projectId, loadTerrain]);

  const onSectionClick = useCallback(
    async (c: [number, number]) => {
      const pts = section.length >= 2 ? [c] : [...section, c];
      setSection(pts);
      if (pts.length < 2) return;
      setSectionMode(false);
      setProfileLoading(true);
      setProfileError(null);
      try {
        setProfile(await api.getProfile(projectId, pts));
      } catch (e) {
        setProfileError((e as Error).message);
      } finally {
        setProfileLoading(false);
      }
    },
    [projectId, section],
  );

  const startSection = () => {
    if (sectionMode) {
      setSectionMode(false);
      return;
    }
    setSection([]);
    setProfile(null);
    setProfileError(null);
    setSectionMode(true);
  };

  const clearSection = () => {
    setSection([]);
    setProfile(null);
    setProfileError(null);
    setSectionMode(false);
  };

  const confirmKp = async (id: string) => {
    setConfirming(id);
    setKpError(null);
    try {
      const updated = await api.confirmKeypoint(projectId, id, true);
      setData((d) => {
        const fc = d.keypoints as FeatureCollection<Point, KeypointProps> | undefined;
        if (!fc) return d;
        return {
          ...d,
          keypoints: {
            ...fc,
            features: fc.features.map((f) =>
              f.properties.id === id ? { ...f, properties: { ...f.properties, ...updated.properties, confirmed: true } } : f,
            ),
          },
        };
      });
    } catch (e) {
      setKpError((e as Error).message);
    } finally {
      setConfirming(null);
    }
  };

  const keypoints = ((data.keypoints as FeatureCollection<Point, KeypointProps> | undefined)?.features ?? [])
    .slice()
    .sort((a, b) => a.properties.id.localeCompare(b.properties.id, undefined, { numeric: true }));
  const confirmedCount = keypoints.filter((k) => k.properties.confirmed).length;
  const progress = jobProgress(job);
  const hasHillshade = !!summary?.dem_tiles_url;

  useAssistantPage("terrain", {
    terrain_model: running ? "building" : summary ? "built" : summaryLoaded ? "missing" : "loading",
    build_progress: running ? job?.step ?? null : undefined,
    summary: summary
      ? {
          elevation_min_m: summary.elevation_min_m, elevation_max_m: summary.elevation_max_m,
          mean_slope_pct: summary.mean_slope_pct, main_valleys: summary.main_valley_count,
          water_leaves_toward: summary.outlet_direction, dem_resolution_m: summary.dem_resolution_m,
          quality_pct: summary.quality,
        }
      : null,
    layers_on: LAYER_TOGGLES.filter((l) => visible[l.key]).map((l) => l.label),
    keypoint_count: keypoints.length,
    keypoints_confirmed: confirmedCount,
    keypoints: keypoints.map((k) => ({
      id: k.properties.id, elevation_m: k.properties.elevation_m, score: k.properties.score, confirmed: k.properties.confirmed,
    })),
    selected_keypoint: selectedKp,
    drawing_section: sectionMode,
    section_profile: profile ? "shown below the map" : null,
  });

  return (
    <div className={styles.layout}>
      {/* Left aside */}
      <aside className={styles.left} aria-label="Layers">
        <div className={styles.intro}>
          <p className="app-eyebrow">
            {project ? `${project.name} · ${formatAcres(project.area_m2)} acres · ` : ""}Step 3 of 5
          </p>
          <h1 className="app-display">Where the water goes.</h1>
          <p className="app-body">
            Contours, flow paths, valleys and ridges from your terrain model. Confirm the keypoints that will anchor
            the keyline design.
          </p>
        </div>

        <fieldset className={styles.layers}>
          <legend className="field-label">Layers</legend>
          {LAYER_TOGGLES.map((l) => {
            const disabled = (l.key === "hillshade" || l.key === "slope") && !hasHillshade;
            return (
              <label key={l.key} className={`${styles.layerRow} ${disabled ? styles.layerDisabled : ""}`}>
                <input
                  type="checkbox"
                  checked={visible[l.key] && !disabled}
                  disabled={disabled}
                  onChange={(e) => setVisible((v) => ({ ...v, [l.key]: e.target.checked }))}
                />
                <span className={`${styles.swatch} ${styles[`sw_${l.swatch}`]}`} aria-hidden="true" />
                <span className={styles.layerLabel}>{l.label}</span>
                {disabled && <span className="app-small">After the terrain model.</span>}
              </label>
            );
          })}
        </fieldset>

        <div className={styles.legend}>
          <p className="field-label">Legend</p>
          <ul>
            <li><span className={`${styles.swatch} ${styles.sw_flow}`} aria-hidden="true" /> Main flow path</li>
            <li><span className={`${styles.swatch} ${styles.sw_flowMinor}`} aria-hidden="true" /> Minor flow path</li>
            <li><span className={`${styles.swatch} ${styles.sw_valleys}`} aria-hidden="true" /> Valley line</li>
            <li><span className={`${styles.swatch} ${styles.sw_ridges}`} aria-hidden="true" /> Ridge line</li>
            <li><span className={`${styles.swatch} ${styles.sw_contoursIndex}`} aria-hidden="true" /> Index contour</li>
            <li><span className={`${styles.swatch} ${styles.sw_contours}`} aria-hidden="true" /> Contour</li>
            <li><span className={`${styles.swatch} ${styles.sw_keypoints}`} aria-hidden="true" /> Keypoint</li>
          </ul>
          {visible.slope && hasHillshade && (
            <div className={styles.slopeLegend} aria-label="Slope classes">
              <p className="field-label">Slope</p>
              <ul>
                {[["Under 5%", 0], ["5–15%", 0.16], ["15–25%", 0.31], ["25–35%", 0.51], ["Over 35%", 0.75]].map(([label, a]) => (
                  <li key={label as string}>
                    <span className={styles.slopeSwatch} style={{ background: `rgba(255,255,255,${a})` }} aria-hidden="true" />
                    {label}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </aside>

      {/* Center */}
      <div className={styles.center}>
        <div className={styles.mapBox}>
          <TerrainMap
            project={project}
            summary={summary}
            data={data}
            visible={{ ...visible, hillshade: visible.hillshade && hasHillshade, slope: visible.slope && hasHillshade }}
            sectionMode={sectionMode}
            section={section}
            onSectionClick={onSectionClick}
            onStartSection={startSection}
            selectedKeypoint={selectedKp}
            onSelectKeypoint={setSelectedKp}
          />
        </div>
        <SectionProfile
          profile={profile}
          loading={profileLoading}
          error={profileError}
          sectionMode={sectionMode}
          onStart={startSection}
          onClear={clearSection}
        />
      </div>

      {/* Right aside */}
      <aside className={styles.right} aria-label="Terrain summary">
        {running && (
          <section className={`card ${styles.panel} fade-in`} aria-live="polite" aria-labelledby="job-title">
            <p className="app-eyebrow">Building terrain model</p>
            <h2 id="job-title" className="app-h2">{job.step ? `${job.step}.` : "Queued."}</h2>
            {job.step_index != null && job.step_count != null && (
              <p className="app-small">Step {job.step_index} of {job.step_count}</p>
            )}
            <div
              className={`progress ${progress == null ? "progress-indeterminate" : ""}`}
              role="progressbar"
              aria-label="Terrain job progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progress == null ? undefined : Math.round(progress * 100)}
            >
              <span style={{ width: `${(progress ?? 0.3) * 100}%` }} />
            </div>
          </section>
        )}

        {job?.status === "failed" && (
          <section className={`card ${styles.panel} ${styles.errorPanel}`} role="alert">
            <p className="app-eyebrow"><IconAlert size={14} /> Terrain job failed</p>
            <p className="app-body">{job.error || "The terrain model could not be built."}</p>
            <Link href={`/projects/${projectId}/survey`} className="btn btn-sm">Back to survey</Link>
          </section>
        )}

        {jobPollError && <p className="error-text" role="alert">Job status unavailable. {jobPollError}</p>}
        {loadError && <p className="error-text" role="alert">{loadError}</p>}

        {summaryLoaded && !summary && !running && job?.status !== "failed" && (
          <section className={`card ${styles.panel}`}>
            <p className="app-eyebrow">No terrain model yet</p>
            <h2 className="app-h2">Bring ground data first.</h2>
            <p className="app-small">Add a survey source, then build the terrain model.</p>
            <Link href={`/projects/${projectId}/survey`} className="btn btn-sm">Go to survey</Link>
          </section>
        )}

        {summary && (
          <section className={`card ${styles.panel}`} aria-labelledby="summary-title">
            <p className="app-eyebrow" id="summary-title">Terrain summary</p>
            <dl className={styles.stats}>
              <div className={styles.statWide}>
                <dt className="field-label">Elevation range</dt>
                <dd>
                  <span className="app-numeral">{formatFeet(summary.elevation_max_m - summary.elevation_min_m)}</span>{" "}
                  <span className="app-small">ft</span>
                  <span className={`app-small ${styles.sub}`}>
                    {formatFeet(summary.elevation_min_m)} to {formatFeet(summary.elevation_max_m)} ft
                  </span>
                </dd>
              </div>
              <div>
                <dt className="field-label">Mean slope</dt>
                <dd><span className={styles.num}>{formatPct(summary.mean_slope_pct, 1)}</span></dd>
              </div>
              <div>
                <dt className="field-label">Main valleys</dt>
                <dd><span className={styles.num}>{summary.main_valley_count}</span></dd>
              </div>
              <div className={styles.statWide}>
                <dt className="field-label">Water leaves the site</dt>
                <dd>
                  <span className={styles.num}>
                    {summary.outlet_direction
                      ? `To the ${DIRECTION_WORDS[summary.outlet_direction] ?? summary.outlet_direction}.`
                      : "—"}
                  </span>
                </dd>
              </div>
              <div className={styles.statWide}>
                <dt className="field-label">DEM resolution</dt>
                <dd className="app-small">{formatResolution(summary.dem_resolution_m)} cells</dd>
              </div>
            </dl>
          </section>
        )}

        {summary && (
          <section className={`card ${styles.panel}`} aria-labelledby="kp-title">
            <p className="app-eyebrow" id="kp-title">Keypoints</p>
            <h2 className="app-h2">
              {keypoints.length ? `${confirmedCount} of ${keypoints.length} confirmed.` : "No keypoints found."}
            </h2>
            {kpError && <p className="error-text" role="alert">{kpError}</p>}
            <ul className={styles.kpList}>
              {keypoints.map((k) => {
                const id = k.properties.id;
                return (
                  <li key={id} className={`${styles.kpRow} ${selectedKp === id ? styles.kpSelected : ""}`}>
                    <button type="button" className={styles.kpSelect} onClick={() => setSelectedKp(id)} aria-pressed={selectedKp === id}>
                      <span className={styles.kpDiamond} data-confirmed={k.properties.confirmed} aria-hidden="true" />
                      <span className={styles.kpText}>
                        <span className={styles.kpId}>{id}</span>
                        <span className="app-small">
                          {formatFeet(k.properties.elevation_m)} ft
                          {k.properties.score != null && ` · score ${Math.round(k.properties.score * 100) / 100}`}
                        </span>
                      </span>
                    </button>
                    {k.properties.confirmed ? (
                      <span className={styles.confirmed}><IconCheck size={16} /> Confirmed</span>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => confirmKp(id)}
                        disabled={confirming === id}
                        aria-label={`Confirm keypoint ${id}`}
                      >
                        {confirming === id ? "Saving." : "Confirm"}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className={styles.next}>
          {summary ? (
            <Link href={`/projects/${projectId}/design`} className="btn btn-primary">
              Design keylines <IconArrowRight />
            </Link>
          ) : (
            <button type="button" className="btn btn-primary" disabled>
              Design keylines <IconArrowRight />
            </button>
          )}
          {summary && keypoints.length > 0 && confirmedCount === 0 && (
            <p className="app-small">Confirm the keypoints you trust; the design step starts from them.</p>
          )}
        </div>
      </aside>
    </div>
  );
}
