"""Metric Catalogue and metric evaluation over HTTP."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import access, grid, metric_registry, metrics, service
from backend.workspace import metric_catalog as mc

router = APIRouter(tags=["workspace-metrics"])


@router.get("/metrics")
async def catalogue(domain: str = Query(""),
                    who: dict[str, Any] = Depends(v4routes.principal)
                    ) -> dict[str, Any]:
    domain_id = access.parse_domain(domain) if domain else ""
    # Counted from the persisted governed objects, not from the code list.
    items = metric_registry.listing(service.objects(), who, domain_id)
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

    obj = metric_registry.get(service.objects(), who, metric_id)
    return {**obj["body"], "object_id": obj["object_id"],
            "object_version": obj["version"],
            "content_hash": obj["content_hash"],
            "used_by": usage.metric_usage(who, metric_id)}


@router.get("/metrics/{metric_id}/lineage")
async def lineage(metric_id: str,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    """Where the number comes from and where it goes (§46 lineage drill)."""
    metric = mc.BY_ID.get(metric_id)
    if metric is None:
        raise HTTPException(404, {"error_code": "UNKNOWN_METRIC",
                                  "message": f"{metric_id} is not defined."})
    from backend.workspace import usage

    svc = service.objects()
    obj = metric_registry.get(svc, who, metric_id)
    sources = []
    for ref in metric["lineage"]:
        relation, _, fld = str(ref).partition(".")
        sources.append({"ref": ref, "relation": relation, "field": fld})
    return {"metric_id": metric_id, "object_id": obj["object_id"],
            "version": obj["version"], "content_hash": obj["content_hash"],
            "sources": sources, "num_sql": metric["num_sql"],
            "den_sql": metric["den_sql"], "evaluator": metric["evaluator"],
            "relative_to": metric["relative_to"],
            "drilldown_dimensions": metric["drilldown_dimensions"],
            "used_by": usage.metric_usage(who, metric_id),
            "versions": [{"version": v["version"],
                          "content_hash": v["content_hash"],
                          "reason": v["lineage"].get("reason", "seeded"),
                          "created_at": v["created_at"]}
                         for v in svc.history(obj["object_id"],
                                              service.principal(who))]}


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
                      filters: str = Query("", max_length=4000),
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    """The exposure rows a book metric is computed over (drill to data),
    optionally narrowed to the dimension value a chart click chose."""
    book = access.book(who, domain)
    if metric_id not in mc.BY_ID:
        raise HTTPException(404, {"error_code": "UNKNOWN_METRIC",
                                  "message": f"{metric_id} is not defined."})
    try:
        parsed = json.loads(filters) if filters else None
    except ValueError as exc:
        raise HTTPException(422, {"error_code": "INVALID_FILTERS",
                                  "message": "filters is a JSON list."}
                            ) from exc
    return grid.query(book, period=period, limit=limit, filters=parsed)


__all__ = ["router"]
