"""The workspace HTTP surface: one router, mounted by `app.create_app` when the
Guided Workspace flag is on, under the V4-served prefix."""

from __future__ import annotations

from fastapi import APIRouter

from backend.workspace import (exchange_api, grid_api, issues_api, metrics_api,
                               objects_api)

PREFIX = "/api/v1/cockpit-v4/workspace"

router = APIRouter(prefix=PREFIX)
router.include_router(exchange_api.router)
router.include_router(objects_api.router)
router.include_router(issues_api.router)
router.include_router(metrics_api.router)
router.include_router(grid_api.router)

__all__ = ["PREFIX", "router"]
