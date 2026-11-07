"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, jobStore, type Project, type Survey, type SurveyKind, type TerrainSummary } from "@/lib/api";
import { formatAcres, formatResolution } from "@/lib/units";
import { ContourArcs } from "../ContourArcs";
import { IconArrowRight, IconDownload, IconDrone, IconFile, IconGlobe, IconPhone, IconUpload } from "../Icons";
import { DataQuality } from "./DataQuality";
import { useAssistantPage } from "@/lib/assistant";
import styles from "./SurveySources.module.css";

type UploadKind = Exclude<SurveyKind, "public_dem">;

const STATUS_LABEL: Record<Survey["status"], string> = {
  uploaded: "Uploaded.",
  processing: "Processing.",
  ready: "Ready.",
  failed: "Failed.",
};
const GRADE_LABEL = { design: "Design grade", planning: "Planning grade", coarse: "Too coarse" } as const;

function SurveyRow({ s }: { s: Survey }) {
  return (
    <li className={styles.surveyRow}>
      <span className={styles.surveyName}>{s.filename ?? (s.kind === "public_dem" ? "USGS 3DEP" : s.kind)}</span>
      <span className="app-small">
        {STATUS_LABEL[s.status]}
        {s.resolution_m != null && ` ${formatResolution(s.resolution_m)} cells.`}
        {s.grade && ` ${GRADE_LABEL[s.grade]}.`}
      </span>
    </li>
  );
}

function uploadWithProgress(projectId: string, kind: UploadKind, file: File, onProgress: (p: number) => void) {
  // XHR for upload progress; fetch has no upload progress events.
  return new Promise<Survey>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${projectId}/surveys`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Survey);
      else {
        const d = (body as { detail?: unknown } | null)?.detail;
        reject(new Error(typeof d === "string" ? d : `Upload failed (${xhr.status}).`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed. Check the connection."));
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    xhr.send(fd);
  });
}

interface UploadState {
  progress: number | null;
  error: string | null;
}

export function SurveySources({ projectId }: { projectId: string }) {
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [terrain, setTerrain] = useState<TerrainSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Record<string, UploadState>>({});
  const [fetchingDem, setFetchingDem] = useState(false);
  const [demError, setDemError] = useState<string | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshSurveys = useCallback(async () => {
    try {
      const list = await api.listSurveys(projectId);
      setSurveys(list);
      return list;
    } catch (e) {
      setLoadError((e as Error).message);
      return [];
    }
  }, [projectId]);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e: Error) => setLoadError(e.message));
    api.getTerrain(projectId).then(setTerrain).catch(() => undefined);
    refreshSurveys();
  }, [projectId, refreshSurveys]);

  // Poll while any survey is still processing.
  useEffect(() => {
    if (!surveys.some((s) => s.status === "uploaded" || s.status === "processing")) return;
    pollRef.current = setTimeout(refreshSurveys, 3000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [surveys, refreshSurveys]);

  const upload = async (slot: string, kind: UploadKind, file: File | undefined) => {
    if (!file) return;
    setUploads((u) => ({ ...u, [slot]: { progress: 0, error: null } }));
    try {
      await uploadWithProgress(projectId, kind, file, (p) =>
        setUploads((u) => ({ ...u, [slot]: { progress: p, error: null } })),
      );
      setUploads((u) => ({ ...u, [slot]: { progress: null, error: null } }));
      refreshSurveys();
    } catch (e) {
      setUploads((u) => ({ ...u, [slot]: { progress: null, error: (e as Error).message } }));
    }
  };

  const onLegacyFile = (file: File | undefined) => {
    if (!file) return;
    const lower = file.name.toLowerCase();
    const kind: UploadKind = lower.endsWith(".tif") || lower.endsWith(".tiff") ? "dem" : "contours";
    upload("legacy", kind, file);
  };

  const fetchDem = async () => {
    setFetchingDem(true);
    setDemError(null);
    try {
      await api.fetchPublicDem(projectId);
      await refreshSurveys();
    } catch (e) {
      setDemError((e as Error).message);
    } finally {
      setFetchingDem(false);
    }
  };

  const build = async () => {
    setBuilding(true);
    setBuildError(null);
    try {
      const job = await api.startTerrainJob(projectId);
      jobStore.set(projectId, job.id);
      router.push(`/projects/${projectId}/terrain?job=${job.id}`);
    } catch (e) {
      setBuildError((e as Error).message);
      setBuilding(false);
    }
  };

  const byKind = (...kinds: SurveyKind[]) => surveys.filter((s) => kinds.includes(s.kind));
  const lidar = byKind("lidar");
  const publicDem = byKind("public_dem");
  const legacy = byKind("dem", "contours");
  const usable = surveys.filter((s) => s.status !== "failed");

  useAssistantPage("survey", {
    sources: surveys.map((s) => ({ kind: s.kind, status: s.status, resolution_m: s.resolution_m, grade: s.grade })),
    usable_sources: usable.length,
    terrain_model: terrain ? "built" : "not built yet",
    design_pct: terrain?.quality.design_pct ?? null,
    planning_pct: terrain?.quality.planning_pct ?? null,
    coarse_pct: terrain?.quality.coarse_pct ?? null,
    busy: building ? "starting the terrain build" : fetchingDem ? "fetching public elevation" : null,
    errors: [demError, buildError, loadError].filter(Boolean),
  });

  return (
    <div className={styles.page}>
      <div className={styles.main}>
        <header className={styles.intro}>
          <p className="app-eyebrow">
            {project ? `${project.name} · ${formatAcres(project.area_m2)} acres · ` : ""}Step 2 of 5
          </p>
          <h1 className="app-display">Bring the best ground data you have.</h1>
          <p className="app-body">
            Drone LiDAR gives design-grade contours. Public elevation fills the gaps. Add as many sources as you
            have; the terrain model uses the finest data for each part of the site.
          </p>
        </header>

        {loadError && <p className="error-text" role="alert">{loadError}</p>}

        <div className={styles.grid}>
          {/* Drone LiDAR */}
          <section className={`card ${styles.source} ${lidar.length ? "card-selected" : ""}`} aria-labelledby="src-lidar">
            <div className={styles.sourceHead}>
              <span className={styles.icon}><IconDrone /></span>
              <span className={styles.tag}>Design grade</span>
            </div>
            <h2 id="src-lidar" className="app-h2">Drone LiDAR upload</h2>
            <p className="app-small">Point cloud from your drone flight. LAS or LAZ, any size.</p>
            <UploadControl
              id="file-lidar"
              accept=".las,.laz"
              label="Upload LAS or LAZ"
              state={uploads.lidar}
              onFile={(f) => upload("lidar", "lidar", f)}
            />
            {lidar.length > 0 && <ul className={styles.surveyList}>{lidar.map((s) => <SurveyRow key={s.id} s={s} />)}</ul>}
          </section>

          {/* USGS 3DEP */}
          <section className={`card ${styles.source} ${publicDem.length ? "card-selected" : ""}`} aria-labelledby="src-3dep">
            <div className={styles.sourceHead}>
              <span className={styles.icon}><IconGlobe /></span>
              <span className={styles.tag}>Planning grade</span>
            </div>
            <h2 id="src-3dep" className="app-h2">USGS 3DEP</h2>
            <p className="app-small">Public elevation for the United States at the best available resolution. Free.</p>
            <div className={styles.controls}>
              <button type="button" className="btn btn-sm" onClick={fetchDem} disabled={fetchingDem}>
                <IconDownload size={16} /> {fetchingDem ? "Fetching." : "Fetch public elevation"}
              </button>
            </div>
            {fetchingDem && <div className="progress progress-indeterminate" aria-label="Fetching public elevation"><span /></div>}
            {demError && <p className="error-text" role="alert">{demError}</p>}
            {publicDem.length > 0 && (
              <ul className={styles.surveyList}>{publicDem.map((s) => <SurveyRow key={s.id} s={s} />)}</ul>
            )}
          </section>

          {/* Phone scan */}
          <section className={`card ${styles.source}`} aria-labelledby="src-phone">
            <div className={styles.sourceHead}>
              <span className={styles.icon}><IconPhone /></span>
              <span className={`${styles.tag} ${styles.tagMuted}`}>Coming soon</span>
            </div>
            <h2 id="src-phone" className="app-h2">Phone LiDAR scan</h2>
            <p className="app-small">Walk the site with a LiDAR-equipped phone to capture swales, ponds and small areas.</p>
            <div className={styles.controls}>
              <button type="button" className="btn btn-sm" disabled>
                <IconUpload size={16} /> Upload scan
              </button>
            </div>
          </section>

          {/* Old survey or drawing (signature motif) */}
          <section
            className={`card-solid ${styles.source} ${styles.legacy} ${legacy.length ? styles.legacySelected : ""}`}
            aria-labelledby="src-legacy"
          >
            <ContourArcs corner="bottom-right" />
            <div className={styles.sourceHead}>
              <span className={styles.icon}><IconFile /></span>
            </div>
            <h2 id="src-legacy" className="app-h2">Old survey or drawing</h2>
            <p className="app-small">A DEM as GeoTIFF, or contour lines as GeoJSON with an elevation attribute.</p>
            <UploadControl
              id="file-legacy"
              accept=".tif,.tiff,.geojson,.json"
              label="Upload TIF or GeoJSON"
              state={uploads.legacy}
              onFile={onLegacyFile}
            />
            {legacy.length > 0 && <ul className={styles.surveyList}>{legacy.map((s) => <SurveyRow key={s.id} s={s} />)}</ul>}
          </section>
        </div>

        <div className={styles.actions}>
          <button type="button" className="btn btn-primary" onClick={build} disabled={building || usable.length === 0}>
            {building ? "Starting." : "Build terrain model"} <IconArrowRight />
          </button>
          {usable.length === 0 && <span className="app-small">Add at least one source to continue.</span>}
          {buildError && <p className="error-text" role="alert">{buildError}</p>}
        </div>
      </div>

      <DataQuality surveys={surveys} terrain={terrain} />
    </div>
  );
}

function UploadControl({
  id,
  accept,
  label,
  state,
  onFile,
}: {
  id: string;
  accept: string;
  label: string;
  state?: UploadState;
  onFile: (f: File | undefined) => void;
}) {
  const busy = state?.progress != null;
  return (
    <div className={styles.controlsCol}>
      <div className={styles.controls}>
        <input
          id={id}
          type="file"
          accept={accept}
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <label htmlFor={id} className="btn btn-sm" aria-disabled={busy || undefined}>
          <IconUpload size={16} /> {label}
        </label>
      </div>
      {busy && (
        <div className={styles.progressRow} aria-live="polite">
          <div
            className="progress"
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round((state!.progress ?? 0) * 100)}
          >
            <span style={{ width: `${(state!.progress ?? 0) * 100}%` }} />
          </div>
          <span className="app-small">{Math.round((state!.progress ?? 0) * 100)}%</span>
        </div>
      )}
      {state?.error && <p className="error-text" role="alert">{state.error}</p>}
    </div>
  );
}
