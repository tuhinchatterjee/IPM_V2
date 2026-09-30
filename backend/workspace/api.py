"""The workspace HTTP surface: one router, mounted by `app.create_app` when the
Guided Workspace flag is on, under the V4-served prefix."""

from __future__ import annotations

from fastapi import APIRouter

from backend.workspace import (exchange_api, grid_api, issues_api, metrics_api,
                               objects_api, scenarios_api, whatif_api)

PREFIX = "/api/v1/cockpit-v4/workspace"

router = APIRouter(prefix=PREFIX)
router.include_router(exchange_api.router)
router.include_router(objects_api.router)
router.include_router(issues_api.router)
router.include_router(metrics_api.router)
router.include_router(grid_api.router)
router.include_router(scenarios_api.router)
router.include_router(whatif_api.router)

# The workspace's saved cohorts become nameable by id in a scenario preview
# (Cockpit or What-If), resolved and hash-verified by the engine.
from backend.cockpit_v4.scenario import cohort_refs  # noqa: E402
from backend.workspace import cohorts  # noqa: E402

cohort_refs.register(cohorts.engine_resolver)

__all__ = ["PREFIX", "router"]
