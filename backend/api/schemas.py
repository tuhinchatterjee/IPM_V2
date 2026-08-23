"""
API response shapes.

Pydantic models rather than bare dictionaries, because these are the contract the
Next.js front end is written against. FastAPI generates the OpenAPI schema from
them, and the TypeScript client mirrors them — so a field renamed here is caught
at the boundary rather than showing up as `undefined` on a screen.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ComponentStatus = Literal["ok", "degraded", "unavailable", "not_configured", "empty"]


class ComponentHealth(BaseModel):
    """The state of one dependency."""

    name: str = Field(description="Component name, e.g. 'postgresql'.")
    status: ComponentStatus
    detail: str = Field(default="", description="Plain-English explanation, shown in the UI.")
    data: dict[str, Any] = Field(default_factory=dict, description="Component-specific facts.")


class HealthResponse(BaseModel):
    """The whole-system health summary the front end polls.

    `status` is the worst of the components, so a single indicator can tell the
    truth about the system without the user reading five separate lights.
    """

    status: Literal["ok", "degraded", "unavailable"]
    app: str
    version: str
    environment: str
    phase: str = Field(description="Which build phase this deployment represents.")
    components: list[ComponentHealth]


class AnalyticalDatasetSummary(BaseModel):
    name: str
    business_name: str
    domain: str
    grain: str
    field_count: int
    periods: list[str] = Field(default_factory=list)
    is_synthetic: bool = Field(
        description="True when the data is synthetic. The UI labels every figure "
        "derived from it, so nobody mistakes a demo number for a real one."
    )


class CatalogResponse(BaseModel):
    """What Data Builder will render, served from the governed catalogue."""

    dataset_count: int
    field_count: int
    domains: dict[str, list[str]]
    datasets: list[AnalyticalDatasetSummary]


class AnalysisSummary(BaseModel):
    """One entry in the Engine Builder Analysis Library."""

    id: str
    name: str
    description: str
    category: str
    version: str
    owner: str
    certification: str
    is_certified: bool = Field(
        description="Drives the blue verification tick. A control, not decoration: "
        "it tells a reader whether the bank has validated this calculation."
    )
    is_runnable: bool


class EngineLibraryResponse(BaseModel):
    total: int
    certified: int
    analyses: list[AnalysisSummary]


class ErrorResponse(BaseModel):
    """Every failure the API returns takes this shape, so the front end has one
    error path rather than one per endpoint."""

    error: str = Field(description="Short machine-readable code.")
    message: str = Field(description="What went wrong, in language a user can act on.")
    detail: dict[str, Any] = Field(default_factory=dict)
