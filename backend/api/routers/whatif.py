"""
What-If over HTTP.

The configuration a scenario runs under — the rating masterscale, the macro
sensitivity matrix, the IFRS 9 policy — is served as data rather than buried in
the calculation, because section 1E asks for it to be VISIBLE. A credit officer
who cannot see the coefficient cannot argue with it, and a coefficient nobody
can argue with is one nobody should believe.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.permissions import RequireAnalyst
from backend.ifrs9 import policy
from backend.whatif import answers as wa
from backend.whatif import engine as wf
from backend.whatif import language as lg
from backend.whatif import masterscale as ms
from backend.whatif import scenarios as sc
from backend.whatif import sensitivity as sv
from backend.whatif import trace as wt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatif", tags=["whatif"])

#: A borrower table longer than this is a download, not a screen.
MAX_ROWS = 500


def _refused(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"error": "invalid_scenario", "message": message})


class ShockIn(BaseModel):
    kind: str = Field(min_length=1, max_length=24)
    magnitude: float = Field(ge=-1000.0, le=1000.0)
    unit: str = Field(default=sc.RELATIVE, max_length=24)
    target: str = Field(default="", max_length=48)


class PopulationIn(BaseModel):
    sectors: list[str] = Field(default_factory=list, max_length=40)
    rating_bands: list[str] = Field(default_factory=list, max_length=20)
    stages: list[int] = Field(default_factory=list, max_length=3)
    borrower_ids: list[str] = Field(default_factory=list, max_length=2000)
    watchlist_only: bool = False


class AssumptionsIn(BaseModel):
    reevaluate_sicr: bool = True
    rating_deterioration_sicr: bool = False
    rating_sicr_notches: int = Field(default=2, ge=1, le=5)
    collateral_to_lgd: bool = True


class RunIn(BaseModel):
    """Either a preconfigured scenario by key, or shocks supplied directly."""

    scenario: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)
    shocks: list[ShockIn] = Field(default_factory=list, max_length=12)
    population: PopulationIn = Field(default_factory=PopulationIn)
    assumptions: AssumptionsIn = Field(default_factory=AssumptionsIn)
    period: str = Field(default="", max_length=24)
    limit: int = Field(default=100, ge=1, le=MAX_ROWS)


class AskIn(BaseModel):
    """A scenario stated in words."""

    question: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=100, ge=1, le=MAX_ROWS)


@router.get("/configuration")
def configuration(_: Any = RequireAnalyst) -> dict[str, Any]:
    """Everything a scenario is computed under, so it can be inspected."""
    return {
        "masterscale": {
            "owner": ms.MASTERSCALE_OWNER,
            "version": ms.MASTERSCALE_VERSION,
            "grades": ms.table(),
            "bands": {name: list(grades) for name, grades in ms.BANDS.items()},
        },
        "sensitivity": sv.describe(),
        "ifrs9_policy": policy.describe(),
        "scenarios": sc.catalogue(),
        "currency": wf.CURRENCY,
        "periods_note": "Scenarios run against the most recent published "
                        "period unless one is named.",
    }


@router.get("/scenarios")
def scenarios(_: Any = RequireAnalyst) -> dict[str, Any]:
    return {"scenarios": sc.catalogue(), "count": len(sc.PRECONFIGURED)}


def _build(body: RunIn) -> sc.Scenario:
    if body.scenario:
        found = sc.scenario(body.scenario)
        if found is None:
            raise _refused(f"No scenario is configured with the key "
                           f"{body.scenario!r}.")
        if not body.shocks and not body.population.model_dump(exclude_defaults=True):
            return found
        base = found
    else:
        base = None

    shocks = tuple(sc.Shock(kind=s.kind, magnitude=s.magnitude, unit=s.unit,
                            target=s.target)
                   for s in body.shocks) or (base.shocks if base else ())
    if not shocks:
        raise _refused("A scenario needs at least one shock. Name a "
                       "preconfigured scenario or supply shocks.")
    for shock in shocks:
        if shock.kind not in (sc.RATING, sc.PD, sc.LGD, sc.EAD, sc.FINANCIAL,
                              sc.COLLATERAL, sc.MACRO):
            raise _refused(f"{shock.kind!r} is not a shock this engine applies.")
        if shock.kind == sc.MACRO and sv.variable(shock.target) is None:
            raise _refused(f"{shock.target!r} is not a variable in the "
                           f"sensitivity matrix.")

    population = sc.Population(
        sectors=tuple(body.population.sectors),
        rating_bands=tuple(body.population.rating_bands),
        stages=tuple(body.population.stages),
        borrower_ids=tuple(body.population.borrower_ids),
        watchlist_only=body.population.watchlist_only)
    if base and population.is_whole_book:
        population = base.population

    return sc.Scenario(
        key=body.scenario or "custom",
        name=body.name or (base.name if base else "Custom scenario"),
        shocks=shocks, population=population,
        assumptions=sc.Assumptions(**body.assumptions.model_dump()),
        severity=(base.severity if base else "custom"),
        rationale=(base.rationale if base else "Composed by the caller."),
        period=body.period)


def _payload(result: wf.Result, limit: int) -> dict[str, Any]:
    return {
        **result.to_dict(),
        "borrowers": wa.borrower_table(result, limit=limit),
        "detail": wt.detail(result),
        "trace": wt.build(result, result.scenario.name).to_dict(),
    }


@router.post("/run")
def run(body: RunIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    try:
        result = wf.run(_build(body), period=body.period)
    except ValueError as exc:
        raise _refused(str(exc)) from exc
    return _payload(result, body.limit)


@router.post("/ask")
def ask(body: AskIn, _: Any = RequireAnalyst) -> dict[str, Any]:
    """A scenario stated in words, read and run."""
    reading = lg.read(body.question)
    if reading.scenario is None:
        return {
            "is_scenario": reading.is_scenario_question,
            "continues_previous": reading.continues_previous,
            "unread": reading.unread,
            "notes": reading.notes,
            "message": "That question does not describe a scenario this "
                       "engine can run. Nothing was guessed.",
        }
    try:
        result = wf.run(reading.scenario)
    except ValueError as exc:
        raise _refused(str(exc)) from exc
    composed = wa.compose_answer(result, reading)
    return {"is_scenario": True, "reading": reading.to_dict(),
            "answer": composed.to_dict(), **_payload(result, body.limit)}


@router.post("/compare")
def compare(keys: list[str], _: Any = RequireAnalyst) -> dict[str, Any]:
    """Several scenarios beside each other, on the same book."""
    wanted = [k for k in keys][:8]
    if not wanted:
        raise _refused("Name at least one scenario to compare.")
    results = []
    for key in wanted:
        found = sc.scenario(key)
        if found is None:
            raise _refused(f"No scenario is configured with the key {key!r}.")
        results.append(wf.run(found))
    frame = wf.compare(results)
    return {"columns": list(frame.columns),
            "rows": frame.values.tolist(),
            "currency": wf.CURRENCY,
            "scenarios": [r.scenario.to_dict() for r in results]}


@router.get("/sensitivity")
def sensitivity(scenario_key: str = Query(default="", max_length=64),
                _: Any = RequireAnalyst) -> dict[str, Any]:
    """The sensitivity table, portfolio-wide or for one scenario's shocks."""
    if not scenario_key:
        return sv.describe()
    found = sc.scenario(scenario_key)
    if found is None:
        raise _refused(f"No scenario is configured with the key "
                       f"{scenario_key!r}.")
    result = wf.run(found)
    return {**sv.describe(), "applied": result.sensitivity_rows}


__all__ = ["router"]
