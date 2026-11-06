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
