// Typed client for the Stage 1 API (docs/api.md). Same-origin /api, proxied by next.config rewrites.
import type { Feature, FeatureCollection, LineString, Point, Polygon } from "geojson";

export type BoundarySource = "parcel" | "upload" | "drawn";

export interface Project {
  id: string;
  name: string;
  address: string;
  boundary: Polygon;
  boundary_source: BoundarySource;
  area_m2: number;
  perimeter_m: number;
  centroid: [number, number];
  bbox: [number, number, number, number];
  created_at: string;
}

export type SurveyKind = "lidar" | "dem" | "contours" | "public_dem";
export type SurveyStatus = "uploaded" | "processing" | "ready" | "failed";
export type Grade = "design" | "planning" | "coarse";

export interface Survey {
  id: string;
  project_id: string;
  kind: SurveyKind;
  filename: string | null;
  status: SurveyStatus;
  resolution_m: number | null;
  grade: Grade | null;
  created_at: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Job {
  id: string;
  project_id: string;
  kind: "terrain";
  status: JobStatus;
  step: string | null;
  step_index: number | null;
  step_count: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export type LayerName = "contours" | "flow" | "valleys" | "ridges" | "keypoints";

export interface TerrainSummary {
  dem_resolution_m: number;
  elevation_min_m: number;
  elevation_max_m: number;
  mean_slope_pct: number;
  outlet: Point | null;
  outlet_direction: string | null;
  main_valley_count: number;
  keypoint_count: number;
  quality: { design_pct: number; planning_pct: number; coarse_pct: number };
  layers: LayerName[];
  dem_url: string | null;
  /** Optional: XYZ terrain-RGB tiles for MapLibre raster-dem. Not in the Stage 1 contract yet. */
  dem_tiles_url?: string | null;
}

export interface ContourProps { elevation_m: number; index: boolean }
export interface FlowProps { accumulation: number; order: number }
export interface KeypointProps { id: string; elevation_m: number; confirmed: boolean; score: number }

export type KeypointFeature = Feature<Point, KeypointProps>;
export type LayerCollection =
  | FeatureCollection<LineString, ContourProps>
  | FeatureCollection<LineString, FlowProps>
  | FeatureCollection<LineString>
  | FeatureCollection<Point, KeypointProps>;

export interface Profile { distance_m: number[]; elevation_m: number[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Could not reach the API.");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (body: { name: string; address: string; boundary: Polygon }) =>
    request<Project>("/projects", { method: "POST", body: json(body) }),
  updateBoundary: (id: string, boundary: Polygon, source: BoundarySource) =>
    request<Project>(`/projects/${id}/boundary`, { method: "PUT", body: json({ boundary, source }) }),

  listSurveys: (id: string) => request<Survey[]>(`/projects/${id}/surveys`),
  uploadSurvey: (id: string, kind: Exclude<SurveyKind, "public_dem">, file: File) => {
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    return request<Survey>(`/projects/${id}/surveys`, { method: "POST", body: fd });
  },
  fetchPublicDem: (id: string) => request<Survey>(`/projects/${id}/surveys/public-dem`, { method: "POST" }),

  startTerrainJob: (id: string, contourIntervalM = 0.6) =>
    request<Job>(`/projects/${id}/terrain-jobs`, { method: "POST", body: json({ contour_interval_m: contourIntervalM }) }),
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  /** Returns null while no terrain job has succeeded (404). */
  getTerrain: async (id: string): Promise<TerrainSummary | null> => {
    try {
      return await request<TerrainSummary>(`/projects/${id}/terrain`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  getLayer: <T extends LayerCollection = LayerCollection>(id: string, layer: LayerName) =>
    request<T>(`/projects/${id}/layers/${layer}`),
  confirmKeypoint: (id: string, kpId: string, confirmed = true) =>
    request<KeypointFeature>(`/projects/${id}/keypoints/${encodeURIComponent(kpId)}`, {
      method: "PATCH",
      body: json({ confirmed }),
    }),
  getProfile: (id: string, coords: [number, number][], samples = 200) => {
    const c = coords.map(([lng, lat]) => `${lng.toFixed(7)},${lat.toFixed(7)}`).join(";");
    return request<Profile>(`/projects/${id}/profile?coords=${encodeURIComponent(c)}&samples=${samples}`);
  },
};

/** Remember the active terrain job per project across the survey -> terrain navigation. */
export const jobStore = {
  key: (projectId: string) => `tr.job.${projectId}`,
  get(projectId: string): string | null {
    try {
      return sessionStorage.getItem(this.key(projectId));
    } catch {
      return null;
    }
  },
  set(projectId: string, jobId: string) {
    try {
      sessionStorage.setItem(this.key(projectId), jobId);
    } catch {
      /* ignore */
    }
  },
  clear(projectId: string) {
    try {
      sessionStorage.removeItem(this.key(projectId));
    } catch {
      /* ignore */
    }
  },
};
