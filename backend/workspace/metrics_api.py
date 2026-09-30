"""Metric Catalogue and metric evaluation over HTTP."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, grid, metrics
from backend.workspace import metric_catalog as mc

router = APIRouter(tags=["workspace-metrics"])


@router.get("/metrics")
async def catalogue(domain: str = Query(""),
                    who: dict[str, Any] = Depends(v4routes.principal)
                    ) -> dict[str, Any]:
    domain_id = access.parse_domain(domain) if domain else ""
    items = metrics.catalogue(domain_id)
    return {"catalog_version": mc.CATALOG_VERSION, "count": len(items),
            "metrics": items, "definition_fields": list(mc.DEFINITION_FIELDS)}


@router.get("/metrics/{metric_id}")
async def definition(metric_id: str,
                     who: dict[str, Any] = Depends(v4routes.principal)
                     ) -> dict[str, Any]:
    metric = mc.BY_ID.get(metric_id)
    if metric is None:
        raise HTTPException(404, {"error_code": "UNKNOWN_METRIC",
                                  "message": f"{metric_id} is not defined."})
    from backend.workspace import usage

    return {**metric, "used_by": usage.metric_usage(who, metric_id)}


class Evaluate(BaseModel):
    domain: str = Field(default="corporate", max_length=20)
    metric_id: str = Field(max_length=12)
    period: str = Field(default="", max_length=12)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    group_by: str = Field(default="", max_length=60)
    series_periods: int = Field(default=0, ge=0, le=20)


@router.post("/metrics/evaluate")
async def evaluate(body: Evaluate,
                   who: dict[str, Any] = Depends(v4routes.principal)
                   ) -> dict[str, Any]:
    book = access.book(who, body.domain)
    out = metrics.evaluate(book, body.metric_id, period=body.period,
                           filters=body.filters or None,
                           group_by=body.group_by)
    if body.series_periods:
        out = {**out, "series": metrics.series(
            book, body.metric_id, periods=body.series_periods,
            filters=body.filters or None,
            end_period=body.period)["points"]}
    return out


@router.get("/metrics/{metric_id}/rows")
async def metric_rows(metric_id: str, domain: str = Query("corporate"),
                      period: str = Query(""), limit: int = Query(50, le=500),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """The exposure rows a book metric is computed over (drill to data)."""
    book = access.book(who, domain)
    if metric_id not in mc.BY_ID:
        raise HTTPException(404, {"error_code": "UNKNOWN_METRIC",
                                  "message": f"{metric_id} is not defined."})
    return grid.query(book, period=period, limit=limit)


__all__ = ["router"]
