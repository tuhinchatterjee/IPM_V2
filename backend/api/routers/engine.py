"""
Engine and Trace API.

    GET  /engine/analyses                 the Analysis Library
    GET  /engine/analyses/{id}            one analysis's full declared contract
    POST /engine/analyses/{id}/execute    run it, returning the result and its Trace
    GET  /engine/periods                  available reporting periods
    GET  /engine/dimensions               available filter dimensions and their values
    GET  /trace/{analysis_run_id}         a stored Trace graph

Execution accepts only a registered analysis id and parameters the contract
allows. There is no endpoint that takes SQL, a file path, or Python — which is
what makes this surface safe for the LLM planner to drive in Phase 3.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst
from backend.data_access import get_catalog, get_data_source
from backend.data_access.context import AnalysisContext
from backend.data_access.protocol import DataAccessError
from backend.engine.contracts import ContractError
from backend.engine.helpers import FACILITY
from backend.engine.registry import UnknownAnalysisError, get_registry
from backend.engine.runner import DatasetNotPublishedError, load_trace, persist_run, run_analysis

logger = logging.getLogger(__name__)

engine_router = APIRouter(prefix="/engine", tags=["engine"])
trace_router = APIRouter(prefix="/trace", tags=["trace"])

# Dimensions offered as filters. Kept to low-cardinality governed fields — a
# filter dropdown listing 673 account ids helps nobody.
FILTER_DIMENSIONS = ["sector", "region", "segment", "product_type", "rating_bucket",
                     "country", "ifrs9_stage", "severity", "collateral_type"]
MAX_DIMENSION_VALUES = 100

# Starlette renamed this constant; support both so the code works either side of
# the rename rather than emitting a deprecation warning on every rejected plan.
# A getattr default is evaluated eagerly, so a nested getattr would still touch
# the deprecated name and emit its warning on every import.
UNPROCESSABLE = (
    status.HTTP_422_UNPROCESSABLE_CONTENT
    if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT")
    else 422
)


class ExecuteIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict,
                                   description="Parameters the analysis contract accepts.")
    period: str | None = Field(default=None,
                               description="Reporting period, or 'latest' / 'earliest'.")
    filters: dict[str, Any] = Field(default_factory=dict,
                                    description="Governed field -> value(s).")
    persist: bool = Field(default=True,
                          description="Store the run and its Trace so it can be reopened.")
    project_id: int | None = None
    chat_id: int | None = None


# ------------------------------------------------------------------- library


@engine_router.get("/analyses", summary="Analysis Library")
def list_analyses(category: str | None = None, certified_only: bool = False) -> dict:
    registry = get_registry()
    contracts = registry.contracts()
    if category:
        contracts = [c for c in contracts if c.category.value == category]
    if certified_only:
        contracts = [c for c in contracts if c.is_certified]
    return {
        "total": len(contracts),
        "certified": sum(1 for c in contracts if c.is_certified),
        "user_defined": sum(1 for c in contracts if c.certification.value == "user_defined"),
        "analyses": [
            {
                "id": c.id, "name": c.name, "description": c.description,
                "category": c.category.value, "version": c.version, "owner": c.owner,
                "certification": c.certification.value,
                "is_certified": c.is_certified, "is_runnable": c.is_runnable,
                "required_datasets": c.required_datasets,
                "requires_compare_period": c.requires_compare_period,
                "supported_visualizations": [v.value for v in c.supported_visualizations],
                "parameter_count": len(c.parameters),
            }
            for c in contracts
        ],
    }


@engine_router.get("/analyses/{analysis_id}", summary="Full analysis definition")
def get_analysis(analysis_id: str) -> dict:
    """Everything Engine Builder shows: inputs, parameters, outputs, validation
    rules, methodology, version, owner and certification."""
    try:
        contract = get_registry().contract(analysis_id)
    except UnknownAnalysisError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "unknown_analysis", "message": str(e)}) from e

    catalog = get_catalog()
    datasets = []
    for name in contract.required_datasets:
        try:
            spec = catalog.dataset(name)
            datasets.append({
                "name": spec.name, "business_name": spec.business_name,
                "domain": spec.domain, "grain": spec.grain,
                "is_synthetic": spec.is_synthetic, "available": True,
            })
        except Exception:
            datasets.append({"name": name, "available": False,
                             "note": "Not published in the governed layer."})

    return {**contract.to_dict(), "datasets": datasets,
            "validation_status": "passing" if contract.is_certified else "not_certified"}


# ------------------------------------------------------------------- execute


@engine_router.post("/analyses/{analysis_id}/execute", summary="Execute an analysis")
def execute(analysis_id: str, payload: ExecuteIn,
            principal: Principal = RequireAnalyst) -> dict:
    """Run one registered analysis and return the result with its Trace graph."""
    try:
        run = run_analysis(
            analysis_id,
            params=payload.params,
            period=payload.period,
            filters=payload.filters,
            user_id=principal.user_id,
        )
    except UnknownAnalysisError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "unknown_analysis", "message": str(e)}) from e
    except ContractError as e:
        raise HTTPException(status_code=UNPROCESSABLE,
                            detail={"error": "contract_violation", "message": str(e)}) from e
    except DatasetNotPublishedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"error": "dataset_not_published", "message": str(e)}) from e
    except DataAccessError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error": "data_access_error", "message": str(e)}) from e

    analysis_run_id = None
    if payload.persist:
        analysis_run_id = persist_run(run, project_id=payload.project_id,
                                      chat_id=payload.chat_id, user_id=principal.user_id)

    body = run.to_dict()
    body["analysis_run_id"] = analysis_run_id

    if run.status == "failed":
        # The trace is returned even on failure: where it stopped is exactly the
        # information someone needs to understand why.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"error": "analysis_failed", "message": run.error or "",
                                    "trace": body["trace"]})
    return body


# --------------------------------------------------------- periods/dimensions


@engine_router.get("/periods", summary="Available reporting periods")
def periods(dataset: str = FACILITY) -> dict:
    source = get_data_source()
    try:
        available = source.periods(dataset)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "unknown_dataset", "message": str(e)}) from e
    return {
        "dataset": dataset,
        "periods": available,
        "latest": available[-1] if available else None,
        "earliest": available[0] if available else None,
        "count": len(available),
        "aliases": {"latest": available[-1] if available else None,
                    "earliest": available[0] if available else None,
                    "previous": available[-2] if len(available) > 1 else None},
    }


@engine_router.get("/dimensions", summary="Available filter dimensions and their values")
def dimensions(dataset: str = FACILITY,
               period: str | None = Query(default=None)) -> dict:
    """What a user (or the planner) may filter on, with the values actually present."""
    source = get_data_source()
    catalog = get_catalog()
    try:
        spec = catalog.dataset(dataset)
        available_periods = source.periods(dataset)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "unknown_dataset", "message": str(e)}) from e

    effective = period or (available_periods[-1] if available_periods else None)
    if effective is None:
        return {"dataset": dataset, "period": None, "dimensions": []}

    ctx = AnalysisContext(period=effective)
    out = []
    for name in FILTER_DIMENSIONS:
        if name not in spec.fields:
            continue
        try:
            frame = source.aggregate(dataset, context=ctx, group_by=[name],
                                     measures={"ead": "sum"}, period=effective)
        except DataAccessError:
            continue
        values = [str(v) for v in frame[name].dropna().tolist()][:MAX_DIMENSION_VALUES]
        field = spec.fields[name]
        out.append({
            "field": name,
            "business_name": field.business_name,
            "definition": field.definition,
            "data_type": field.data_type,
            "value_count": len(values),
            "values": values,
        })
    return {"dataset": dataset, "period": effective, "dimensions": out}


# --------------------------------------------------------------------- trace


@trace_router.get("/{analysis_run_id}", summary="Retrieve the Trace for an analysis run")
def get_trace(analysis_run_id: int, version: int | None = None) -> dict:
    trace = load_trace(analysis_run_id, version)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "trace_not_found",
                    "message": f"No stored Trace for analysis run {analysis_run_id}."},
        )
    return trace
