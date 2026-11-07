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
  /** Terrarium-encoded elevation tiles for MapLibre raster-dem (hillshade and 3D). */
  dem_tiles_url?: string | null;
  /** Slope classes as white-with-opacity tiles. */
  slope_tiles_url?: string | null;
  /** [west, south, east, north] of the terrain model. */
  dem_bounds?: [number, number, number, number] | null;
}

// ---- Stage 2: design, estimate, export ----------------------------------------------------------

export type DesignKind = "keyline" | "rip" | "swale";

export interface DesignProps {
  id: string;
  kind: DesignKind;
  label: string;
  group_id: string | null;
  length_m: number;
  draft?: boolean;
  notes?: string[];
  keypoint_id?: string;
  pass?: number;
  position?: "above" | "below";
  fall_to_ridges_min?: number | null;
  steepest_grade?: number | null;
  elevation_m?: number;
  width_m?: number;
  depth_m?: number;
  cut_volume_m3?: number;
  storage_gal?: number;
  catchment_m2?: number;
  terrain_slope_max_pct?: number;
  [k: string]: unknown;
}

export type DesignFeature = Feature<LineString, DesignProps>;
export type DesignCollection = FeatureCollection<LineString, DesignProps>;

export interface KeylineRequest {
  keypoint_id: string;
  grade: number;
  spacing_m: number;
  extent: "site" | "valley";
  pattern: "parallel" | "graded" | "none";
  allow_planning: boolean;
}

export interface KeylineResult {
  group_id: string;
  keyline: DesignFeature;
  rip_count: number;
  rip_length_m: number;
  area_treated_m2: number;
  terrain_grade: "design" | "planning";
  notes: string[];
}

export interface SwaleRequest {
  start: [number, number];
  end: [number, number];
  width_m: number;
  depth_m: number;
  berm: boolean;
  allow_planning: boolean;
}

export interface CostItem {
  item: string;
  label: string;
  unit: string;
  rate_low: number;
  rate_high: number;
  note: string | null;
  custom: boolean;
}

export interface EstimateLine {
  item: string;
  label: string;
  quantity: number;
  unit: string;
  rate_low: number;
  rate_high: number;
  total_low: number;
  total_high: number;
  basis: string;
}

export interface Estimate {
  lines: EstimateLine[];
  build_low: number;
  build_high: number;
  design_fee_low: number;
  design_fee_high: number;
  contingency_pct: number;
  contingency_low: number;
  contingency_high: number;
  total_low: number;
  total_high: number;
  quantities: Record<string, number>;
  draft: boolean;
  note: string;
}

export interface ChatMessage { role: "user" | "assistant"; content: string }

export interface Proposal {
  id: string;
  kind: "keyline" | "swale";
  params: Record<string, unknown>;
  preview: DesignCollection;
  summary: Record<string, unknown> & { notes?: string[] };
  status: "draft" | "accepted" | "discarded";
  created_at: string;
}

export interface AssistantReply {
  reply: string;
  model: string;
  tool_log: { tool: string; input: Record<string, unknown>; error?: string | null }[];
  proposals: Proposal[];
  citations: { title: string; url: string | null; code: string | null }[];
}

export interface KnowledgeHit {
  chunk_id: string; title: string; code: string | null; url: string | null; source: string; license: string;
  heading: string | null; body: string; score: number;
  link_only: boolean; work_license: string | null;
}

export interface GeocodeResult { label: string; lng: number; lat: number; source: string }
export interface Parcel { apn: string | null; address: string | null; acres: number | null; boundary: Polygon; source: string }

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

  getDesign: (id: string) => request<DesignCollection>(`/projects/${id}/design`),
  createKeyline: (id: string, body: KeylineRequest) =>
    request<KeylineResult>(`/projects/${id}/design/keylines`, { method: "POST", body: json(body) }),
  createSwale: (id: string, body: SwaleRequest) =>
    request<DesignFeature>(`/projects/${id}/design/swales`, { method: "POST", body: json(body) }),
  deleteElement: (id: string, elementId: string) =>
    request<void>(`/projects/${id}/design/elements/${elementId}`, { method: "DELETE" }),
  elementProfile: (id: string, elementId: string) =>
    request<Profile>(`/projects/${id}/design/elements/${elementId}/profile`),

  getEstimate: (id: string, contingencyPct = 15) =>
    request<Estimate>(`/projects/${id}/estimate?contingency_pct=${contingencyPct}`),
  listCostItems: () => request<CostItem[]>("/cost-items"),
  updateCostItem: (item: string, rate_low: number, rate_high: number) =>
    request<CostItem>(`/cost-items/${encodeURIComponent(item)}`, { method: "PUT", body: json({ rate_low, rate_high }) }),
  resetCostItem: (item: string) => request<void>(`/cost-items/${encodeURIComponent(item)}`, { method: "DELETE" }),

  askAssistant: (id: string, messages: ChatMessage[], allowPlanning: boolean) =>
    request<AssistantReply>(`/projects/${id}/assistant`, { method: "POST", body: json({ messages, allow_planning: allowPlanning }) }),
  listProposals: (id: string) => request<Proposal[]>(`/projects/${id}/assistant/proposals`),
  acceptProposal: (id: string, pid: string) =>
    request<Proposal>(`/projects/${id}/assistant/proposals/${pid}/accept`, { method: "POST" }),
  discardProposal: (id: string, pid: string) =>
    request<void>(`/projects/${id}/assistant/proposals/${pid}/discard`, { method: "POST" }),
  searchKnowledge: (q: string) => request<KnowledgeHit[]>(`/knowledge/search?q=${encodeURIComponent(q)}`),

  geocode: (q: string) => request<GeocodeResult[]>(`/geocode?q=${encodeURIComponent(q)}`),
  parcelAt: (lng: number, lat: number) => request<Parcel>(`/parcels/at?lng=${lng}&lat=${lat}`),
};

/** Download links (same-origin, so the session cookie rides along through the proxy). */
export const exportUrl = {
  estimateXlsx: (id: string, pct = 15) => `${BASE}/projects/${id}/estimate.xlsx?contingency_pct=${pct}`,
  pdf: (id: string, pct = 15) => `${BASE}/projects/${id}/export/plan.pdf?contingency_pct=${pct}`,
  geojson: (id: string) => `${BASE}/projects/${id}/export/geojson`,
  shapefile: (id: string) => `${BASE}/projects/${id}/export/shapefile`,
  kml: (id: string) => `${BASE}/projects/${id}/export/kml`,
  dxf: (id: string) => `${BASE}/projects/${id}/export/dxf`,
  guidance: (id: string, format: "geojson" | "shapefile") => `${BASE}/projects/${id}/export/guidance?format=${format}`,
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
