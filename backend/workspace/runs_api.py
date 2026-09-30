"""HTTP surface of What-If runs (P6): confirm, choose the method, execute."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.cockpit_v4 import routes as v4routes
from backend.workspace import runs, service

router = APIRouter(tags=["workspace-whatif-runs"])


class Baseline(BaseModel):
    mode: str = Field(pattern="^(SOURCE_BASELINE|PRIOR_SCENARIO)$")
    parent_run_id: str = Field(default="", max_length=80)


class CreateRun(BaseModel):
    scenario_id: str = Field(min_length=4, max_length=80)
    scenario_version: int | None = None
    cohort_id: str = Field(default="", max_length=80)
    cohort_version: int | None = None
    session_id: str = Field(default="", max_length=80)
    baseline: Baseline | None = None
    entry: str = Field(default="whatif",
                       pattern="^(whatif|library|cockpit|messages)$")


class ChooseBaseline(BaseModel):
    baseline: Baseline


class Confirm(BaseModel):
    digest: str = Field(min_length=16, max_length=128)


class ChooseMethod(BaseModel):
    methods: list[str] = Field(default_factory=list, max_length=4)
    user_assumption: dict[str, Any] | None = None


def _baseline(b: Baseline | None) -> dict[str, Any] | None:
    if b is None:
        return None
    out: dict[str, Any] = {"mode": b.mode}
    if b.parent_run_id:
        out["parent_run_id"] = b.parent_run_id
    return out


@router.post("/whatif/runs", status_code=201)
async def create_run(body: CreateRun,
                     who: dict[str, Any] = Depends(v4routes.principal)
                     ) -> dict[str, Any]:
    return runs.create(service.objects(), who, scenario_id=body.scenario_id,
                       scenario_version=body.scenario_version,
                       cohort_id=body.cohort_id,
                       cohort_version=body.cohort_version,
                       session_id=body.session_id,
                       baseline=_baseline(body.baseline), entry=body.entry)


@router.get("/whatif/runs")
async def list_runs(session_id: str = Query("", max_length=80),
                    domain: str = Query("corporate"),
                    who: dict[str, Any] = Depends(v4routes.principal)
                    ) -> dict[str, Any]:
    return {"runs": runs.session_listing(service.objects(), who,
                                         session_id=session_id,
                                         domain=domain)}


@router.get("/whatif/runs/{run_id}")
async def get_run(run_id: str,
                  who: dict[str, Any] = Depends(v4routes.principal)
                  ) -> dict[str, Any]:
    return runs.get(service.objects(), who, run_id)


@router.post("/whatif/runs/{run_id}/baseline")
async def choose_baseline(run_id: str, body: ChooseBaseline,
                          who: dict[str, Any] = Depends(v4routes.principal)
                          ) -> dict[str, Any]:
    return runs.choose_baseline(service.objects(), who, run_id,
                                _baseline(body.baseline))


@router.post("/whatif/runs/{run_id}/confirm")
async def confirm_run(run_id: str, body: Confirm,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return runs.confirm(service.objects(), who, run_id, body.digest)


@router.post("/whatif/runs/{run_id}/method")
async def choose_method(run_id: str, body: ChooseMethod,
                        who: dict[str, Any] = Depends(v4routes.principal)
                        ) -> dict[str, Any]:
    return runs.choose_method(service.objects(), who, run_id, body.methods,
                              body.user_assumption)


@router.post("/whatif/runs/{run_id}/execute")
async def execute_run(run_id: str,
                      who: dict[str, Any] = Depends(v4routes.principal)
                      ) -> dict[str, Any]:
    return runs.execute(service.objects(), who, run_id)


@router.post("/whatif/runs/{run_id}/rerun", status_code=201)
async def rerun(run_id: str,
                who: dict[str, Any] = Depends(v4routes.principal)
                ) -> dict[str, Any]:
    return runs.rerun(service.objects(), who, run_id)


__all__ = ["router"]
