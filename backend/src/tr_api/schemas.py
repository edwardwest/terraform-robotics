"""Request and response models. Keep in step with docs/api.md and apps/web/src/lib/api.ts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    group: Literal["design", "plan"] = "design"  # computed from design geometry, or a planning allowance


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


AssistantStep = Literal["site", "goals", "survey", "terrain", "ideas", "design", "estimate"]


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AssistantRequest(BaseModel):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=40)
    allow_planning: bool = False
    step: AssistantStep = "design"
    page_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("page_context")
    @classmethod
    def small_context(cls, v):
        if len(json.dumps(v, default=str)) > 4000:
            raise ValueError("page_context is too large (4,000 characters at most)")
        return v

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, v):
        if v[-1].role != "user":
            raise ValueError("The last message must be from the user")
        return v


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
    brief_suggestion: dict[str, Any] | None = None  # partial goals brief the person can apply on the Goals step


# ---- Goals brief, intervention ideas and the plan ---------------------------------------------------


def _check_options(question: str, values: list[str] | str | None):
    from tr_kb import interventions as iv

    if values is None:
        return values
    allowed = iv.option_ids(question) if question != "goals" else set(iv.goal_ids())
    bad = [v for v in ([values] if isinstance(values, str) else values) if v not in allowed]
    if bad:
        raise ValueError(f"Unknown {question}: {', '.join(bad)}")
    return values


class BriefUpdate(BaseModel):
    """What the person wants from the land. Every field is optional; goals are ranked, most important first."""

    goals: list[str] | None = Field(default=None, max_length=5)
    setting: str | None = None
    has_buildings: bool | None = None
    water_sources: list[str] | None = Field(default=None, max_length=5)
    annual_rainfall_mm: float | None = Field(default=None, ge=0, le=6000)
    budget: str | None = None
    timeline: str | None = None
    maintenance: str | None = None
    constraints: list[str] | None = Field(default=None, max_length=5)
    vision: str | None = Field(default=None, max_length=1500)

    @field_validator("goals", "water_sources", "constraints")
    @classmethod
    def unique(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError("List items must be unique")
        return v

    @field_validator("goals")
    @classmethod
    def known_goals(cls, v):
        return _check_options("goals", v)

    @field_validator("setting", "budget", "timeline", "maintenance", "water_sources", "constraints")
    @classmethod
    def known_options(cls, v, info):
        return _check_options(info.field_name, v)


class Brief(BriefUpdate):
    updated_at: datetime | None = None


class ReferenceLink(BaseModel):
    id: str
    title: str
    url: str | None
    work_license: str


class Recommendation(BaseModel):
    id: str
    title: str
    category: str
    phase: str
    summary: str
    fit: Literal["good", "possible", "not_suited"]
    score: float
    matched_goals: list[str]
    reasons: list[str]
    concerns: list[str]
    unknowns: list[str]
    cautions: list[str]
    maintenance: Literal["low", "medium", "high"]
    cost_tier: int
    nrcs: list[str]
    rules: list[str]
    references: list[ReferenceLink]
    tool: Literal["keyline", "swale"] | None
    quantity: dict[str, Any] | None
    has_allowance: bool
    selected: bool


class Recommendations(BaseModel):
    brief_complete: bool
    site: dict[str, Any]
    items: list[Recommendation]


class PlanItemUpdate(BaseModel):
    quantity: float | None = Field(default=None, ge=0, le=1e9)
    notes: str | None = Field(default=None, max_length=1000)


class PlanItem(BaseModel):
    intervention_id: str
    title: str
    category: str
    phase: str
    tool: Literal["keyline", "swale"] | None
    quantity_basis: Literal["area_m2", "length_m", "volume_m3", "count"] | None
    quantity: float | None
    notes: str | None
    cost_item: str | None
    created_at: datetime
    placed: int = 0                          # master plan features that place this intervention
    measured_quantity: float | None = None   # from those features, in quantity_basis; replaces quantity in the estimate


# ---- Master plan features ----------------------------------------------------------------------------


class SpeciesRef(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)  # USDA PLANTS symbol; names are filled in from the table
    scientific_name: str | None = None
    common_name: str | None = None


class PlanFeatureProps(BaseModel):
    """Settings; which ones a type takes is in the library (`fields`). Metric."""
    model_config = ConfigDict(extra="forbid")
    species: list[SpeciesRef] | None = Field(default=None, max_length=30)
    plant_spacing_m: float | None = Field(default=None, gt=0.1, le=50)
    row_spacing_m: float | None = Field(default=None, gt=0.1, le=50)
    rows: int | None = Field(default=None, ge=1, le=10)
    height_m: float | None = Field(default=None, gt=0, le=80)
    roof: Literal["gable", "hip", "shed", "flat"] | None = None
    capacity_m3: float | None = Field(default=None, ge=0, le=100000)
    rows_pattern: Literal["straight", "contour"] | None = None  # planted areas: straight rows or rows on contour
    notes: str | None = Field(default=None, max_length=1000)


class PlanFeatureCreate(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    geometry: dict
    label: str | None = Field(default=None, max_length=80)
    status: Literal["proposed", "existing"] | None = None
    build_phase: int | None = Field(default=None, ge=1, le=3)
    props: PlanFeatureProps | None = None


class PlanFeatureUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=40)
    geometry: dict | None = None
    label: str | None = Field(default=None, max_length=80)
    status: Literal["proposed", "existing"] | None = None
    build_phase: int | None = Field(default=None, ge=1, le=3)
    props: PlanFeatureProps | None = None


class PlanFeatureProperties(BaseModel):
    id: str
    type: str
    type_label: str
    category: str
    color: str
    label: str | None
    status: Literal["proposed", "existing"]
    build_phase: int
    props: dict
    intervention: str | None
    area_m2: float | None
    length_m: float | None
    perimeter_m: float | None
    plant_count: int | None
    created_at: str
    updated_at: str


class PlanFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: PlanFeatureProperties


class PlanFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PlanFeature]


# ---- Master plan sheet ------------------------------------------------------------------------------


class PlanSheetSettings(BaseModel):
    """How the master plan sheet is drawn. Label positions are fractions of the sheet's width and height, so they
    survive a change of sheet size; keys are the label text (upper case) as drawn."""
    model_config = ConfigDict(extra="forbid")
    size: Literal["11x17", "24x36"] = "11x17"
    title: str = Field(default="Master plan", max_length=60)
    subtitle: str | None = Field(default=None, max_length=120)  # defaults to the project address
    prepared_by: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=800)
    base: Literal["aerial", "terrain", "plain"] = "aerial"
    contours: bool = True
    labels: Literal["callouts", "on_features", "off"] = "callouts"
    phases: int = Field(default=0, ge=0, le=3)  # 0: all; n: phases 1 to n
    show_existing: bool = True
    hidden_categories: list[str] = Field(default_factory=list, max_length=20)
    hidden_labels: list[str] = Field(default_factory=list, max_length=500)
    label_positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    schedule: bool = True

    @field_validator("label_positions")
    @classmethod
    def _on_sheet(cls, v: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
        if len(v) > 500:
            raise ValueError("Too many label positions")
        for key, (x, y) in v.items():
            if len(key) > 120 or not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("Label positions are fractions of the sheet, from 0 to 1")
        return v


# ---- Master plan site: zones, sectors, contour lines, checks ----------------------------------------


class Wind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(default="Prevailing wind", max_length=40)
    from_deg: float = Field(ge=0, lt=360)  # the direction the wind comes FROM, degrees clockwise from north


class PlanSiteSettings(BaseModel):
    """Zones 1-4 (distance out from the house, metres), winds and fire direction, and which overlays the map shows."""
    model_config = ConfigDict(extra="forbid")
    # 50, 150, 400 and 1,000 ft
    zone_radii_m: list[float] = Field(default_factory=lambda: [15.24, 45.72, 121.92, 304.8], min_length=4, max_length=4)
    zone_center: str | None = None  # a house feature id; None: the first house, else the middle of the property
    winds: list[Wind] = Field(default_factory=list, max_length=4)
    fire_from_deg: float | None = Field(default=None, ge=0, lt=360)
    show_zones: bool = False
    show_sectors: bool = False

    @field_validator("zone_radii_m")
    @classmethod
    def _rising(cls, v: list[float]) -> list[float]:
        if any(r <= 0 or r > 5000 for r in v) or any(b <= a for a, b in zip(v, v[1:])):
            raise ValueError("Zone distances must rise from zone 1 to zone 4, each up to 5,000 m")
        return v


class ContourLineRequest(BaseModel):
    start: tuple[float, float]  # lon, lat
    end: tuple[float, float]
