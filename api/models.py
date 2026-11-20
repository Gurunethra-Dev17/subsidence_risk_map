"""Pydantic models shared by the API scaffold and endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """C4 standard error response envelope."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class Ward(BaseModel):
    model_config = ConfigDict(extra="allow")

    ward_id: str
    ward_name: str
    status: Literal["ranked", "insufficient_data"]
    n_buildings: int = Field(ge=0)
    n_buildings_with_data: int = Field(ge=0)
    coverage_pct: float = Field(ge=0, le=100)
    flags: list[
        Literal[
            "sparse_points",
            "groundwater_missing",
            "small_ward",
            "low_coverage",
            "boundary_vintage",
        ]
    ]
    share_sinking_gt4: float | None = Field(default=None, ge=0, le=1)
    vlm_median_mm_yr: float | None = None
    beta_p90_horizon: float | None = None
    beta_p90_ratio_horizon: str | None = None
    gw_stage_pct: float | None = None
    gw_category: str | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    rank: int | None = Field(default=None, ge=1)
    rank_p05: int | None = Field(default=None, ge=1)
    rank_p95: int | None = Field(default=None, ge=1)
    histogram: dict[str, Any] | None = None


class WardPage(BaseModel):
    items: list[Ward]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CellProperties(BaseModel):
    cell_id: str
    ward_id: str | None
    n_buildings: int = Field(ge=0)
    suppressed: bool
    vlm_median_mm_yr: float | None
    beta_p90_horizon: float | None
    share_sinking_gt4: float | None
    cell_score: float | None = Field(ge=0, le=100)
    cell_rank_in_ward: int | None = Field(ge=1)


class CellFeature(BaseModel):
    type: Literal["Feature"]
    geometry: dict[str, Any] | None
    properties: CellProperties


class CellFeatureCollection(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["FeatureCollection"]
    features: list[CellFeature]


class ValidationSummary(BaseModel):
    contract: Literal["C3@1.0"]
    generated_utc: str
    vt_consistency: dict[str, Any]
    collapse_check: dict[str, Any]
    hotspot_check: list[dict[str, Any]]
    robustness: dict[str, Any]
    fresh_data_check: dict[str, Any]
    figures: list[dict[str, Any]]
