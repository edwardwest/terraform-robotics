"""Request and response models. Keep in step with docs/api.md and apps/web/src/lib/api.ts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from shapely.geometry import shape

BoundarySource = Literal["parcel", "upload", "drawn"]


class Polygon(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]

    @field_validator("coordinates")
    @classmethod
    def valid_ring(cls, v):
        if not v or len(v[0]) < 4:
            raise ValueError("A polygon needs at least three distinct points")
        geom = shape({"type": "Polygon", "coordinates": v})
        if not geom.is_valid:
            raise ValueError("Polygon is self-intersecting or otherwise invalid")
        for lng, lat, *_ in v[0]:
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                raise ValueError("Coordinates must be longitude, latitude in degrees")
        return v


class User(BaseModel):
    id: UUID
    clerk_user_id: str
    email: str | None
    name: str | None
    created_at: datetime


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    boundary: Polygon | None = None
    boundary_source: BoundarySource = "drawn"


class BoundaryUpdate(BaseModel):
    boundary: Polygon
    source: BoundarySource = "drawn"


class Project(BaseModel):
    id: UUID
    name: str
    address: str | None
    boundary: dict | None
    boundary_source: str | None
    area_m2: float | None
    perimeter_m: float | None
    centroid: list[float] | None
    bbox: list[float] | None
    created_at: datetime


SurveyKind = Literal["lidar", "dem", "contours", "public_dem"]


class Survey(BaseModel):
    id: UUID
    project_id: UUID
    kind: SurveyKind
    filename: str | None
    status: Literal["uploaded", "processing", "ready", "failed"]
    resolution_m: float | None
    grade: Literal["design", "planning", "coarse"] | None
    error: str | None = None
    created_at: datetime


class TerrainJobCreate(BaseModel):
    contour_interval_m: float = Field(default=0.6, gt=0.05, le=50)


class Job(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    status: Literal["queued", "running", "succeeded", "failed"]
    step: str | None
    step_index: int
    step_count: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class KeypointUpdate(BaseModel):
    confirmed: bool


class Profile(BaseModel):
    distance_m: list[float]
    elevation_m: list[float | None]


class TerrainSummary(BaseModel):
    dem_resolution_m: float
    elevation_min_m: float
    elevation_max_m: float
    mean_slope_pct: float
    outlet: dict[str, Any]
    outlet_direction: str
    main_valley_count: int
    keypoint_count: int
    quality: dict[str, float]
    layers: list[str]
    dem_url: str
    dem_tiles_url: str | None = None
    slope_tiles_url: str | None = None
    dem_bounds: list[float] | None = None  # [west, south, east, north] of the terrain model


# ---- Stage 2: design --------------------------------------------------------------------------

LngLat = tuple[float, float]


class KeylineCreate(BaseModel):
    keypoint_id: str = Field(min_length=1, max_length=20)
    grade: float = Field(default=1 / 300, gt=0, le=0.05, description="fall per metre along the line")
    spacing_m: float = Field(default=5.0, ge=0.5, le=100)
    extent: Literal["site", "valley"] = "site"
    pattern: Literal["parallel", "graded", "none"] = "parallel"
    max_lines: int = Field(default=300, ge=1, le=600)
    allow_planning: bool = False


class SwaleCreate(BaseModel):
    start: LngLat
    end: LngLat
    width_m: float = Field(default=1.8, gt=0, le=20)
    depth_m: float = Field(default=0.45, gt=0, le=5)
    berm: bool = True
    allow_planning: bool = False


class DesignFeature(BaseModel):
    type: Literal["Feature"]
    geometry: dict[str, Any]
    properties: dict[str, Any]


class KeylineResult(BaseModel):
    group_id: str
    keyline: DesignFeature
    rip_count: int
    rip_length_m: float
    area_treated_m2: float
    terrain_grade: Literal["design", "planning"]
    notes: list[str]


# ---- Estimate ---------------------------------------------------------------------------------


class CostItem(BaseModel):
    item: str
    label: str
    unit: str
    rate_low: float
    rate_high: float
    note: str | None = None
    custom: bool = False


class CostItemUpdate(BaseModel):
    rate_low: float = Field(ge=0)
    rate_high: float = Field(ge=0)

    @field_validator("rate_high")
    @classmethod
    def ordered(cls, v, info):
        low = info.data.get("rate_low")
        if low is not None and v < low:
            raise ValueError("rate_high must be at least rate_low")
        return v


class EstimateLine(BaseModel):
    item: str
    label: str
    quantity: float
    unit: str
    rate_low: float
    rate_high: float
    total_low: float
    total_high: float
    basis: str


class Estimate(BaseModel):
    lines: list[EstimateLine]
    build_low: float
    build_high: float
    design_fee_low: float
    design_fee_high: float
    contingency_pct: float
    contingency_low: float
    contingency_high: float
    total_low: float
    total_high: float
    quantities: dict[str, float]
    draft: bool
    note: str


# ---- Parcels and geocoding ----------------------------------------------------------------------


class GeocodeResult(BaseModel):
    label: str
    lng: float
    lat: float
    source: str


class Parcel(BaseModel):
    apn: str | None
    address: str | None
    acres: float | None
    boundary: dict[str, Any]
    source: str


# ---- AI assistant ---------------------------------------------------------------------------------


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AssistantRequest(BaseModel):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=40)
    allow_planning: bool = False


class Proposal(BaseModel):
    id: str
    kind: Literal["keyline", "swale"]
    params: dict[str, Any]
    preview: dict[str, Any]
    summary: dict[str, Any]
    status: Literal["draft", "accepted", "discarded"]
    created_at: datetime


class AssistantReply(BaseModel):
    reply: str
    model: str
    tool_log: list[dict[str, Any]]
    proposals: list[Proposal]
    citations: list[dict[str, Any]]
