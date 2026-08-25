"""
The CreditProbe API — FastAPI application.

This is the boundary the Next.js front end talks to. Putting every capability
behind HTTP rather than letting screens call Python directly is what makes the
front end replaceable and the engine reusable (docs/ARCHITECTURE.md §7).

Run it in development with:

    python -m backend.api            # or: scripts/dev.sh api

Interactive API documentation is served at /docs when ENV=dev.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import auth as auth_router
from backend.api.routers import ask as ask_router
from backend.api.routers import data_builder as data_builder_router
from backend.api.routers import early_warning as early_warning_router
from backend.api.routers import engine as engine_router
from backend.api.routers import health as health_router
from backend.api.routers import hierarchy as hierarchy_router
from backend.api.routers import lenses as lenses_router
from backend.api.routers import playbooks as playbooks_router
from backend.api.routers import users as users_router
from backend.api.routers import workspace as workspace_router
from backend.api.schemas import ErrorResponse
from backend.config import settings
from backend.data_access.protocol import DataAccessError
from backend.engine.contracts import ContractError
from backend.engine.registry import UnknownAnalysisError
from backend.logging_setup import init_logging

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    init_logging()

    app = FastAPI(
        title=health_router.APP_NAME,
        version=health_router.APP_VERSION,
        description=(
            "Credit Portfolio Intelligence & Monitoring.\n\n"
            "The deterministic engine is the source of truth for every figure; "
            "the language model plans and narrates but never calculates."
        ),
        # Interactive docs are a development convenience, not a production surface.
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_prod else None,
    )

    # The browser calls the API from a different port in development
    # (Next.js on 3000, FastAPI on 8000), which the browser treats as a
    # different origin and blocks by default unless the API opts in.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        """Tag every request with an id and record how long it took.

        The id is echoed in the response header and will be written onto trace
        nodes, so a slow or wrong answer on screen can be traced back to its
        server-side log lines.
        """
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = str(elapsed_ms)
        if elapsed_ms > 2000:
            logger.warning("Slow request %s %s took %dms", request.method, request.url.path, elapsed_ms)
        return response

    # ---------------------------------------------------------------- errors
    # One error shape for the whole API, so the front end has a single error path.
    # Messages are written for a user to read, because several of these surface
    # directly in the AI Cockpit.

    @app.exception_handler(UnknownAnalysisError)
    async def _unknown_analysis(request: Request, exc: UnknownAnalysisError):
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(error="unknown_analysis", message=str(exc)).model_dump(),
        )

    @app.exception_handler(ContractError)
    async def _contract_error(request: Request, exc: ContractError):
        # 422: the request was understood but violates the analytical contract.
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(error="contract_violation", message=str(exc)).model_dump(),
        )

    @app.exception_handler(DataAccessError)
    async def _data_error(request: Request, exc: DataAccessError):
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(error="data_access_error", message=str(exc)).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak a stack trace to the browser; log it in full instead.
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("Unhandled error on %s (request %s)", request.url.path, request_id)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="internal_error",
                message="Something went wrong on the server. The error has been logged.",
                detail={"request_id": request_id},
            ).model_dump(),
        )

    # ---------------------------------------------------------------- routes

    app.include_router(auth_router.router, prefix=API_PREFIX)
    app.include_router(health_router.router, prefix=API_PREFIX)
    app.include_router(users_router.router, prefix=API_PREFIX)
    app.include_router(data_builder_router.router, prefix=API_PREFIX)
    app.include_router(engine_router.engine_router, prefix=API_PREFIX)
    app.include_router(engine_router.trace_router, prefix=API_PREFIX)
    app.include_router(ask_router.router, prefix=API_PREFIX)
    app.include_router(ask_router.trace_edit_router, prefix=API_PREFIX)
    app.include_router(early_warning_router.router, prefix=API_PREFIX)
    app.include_router(hierarchy_router.projects_router, prefix=API_PREFIX)
    app.include_router(hierarchy_router.threads_router, prefix=API_PREFIX)
    app.include_router(hierarchy_router.analyses_router, prefix=API_PREFIX)
    app.include_router(lenses_router.router, prefix=API_PREFIX)
    app.include_router(playbooks_router.router, prefix=API_PREFIX)
    app.include_router(workspace_router.router, prefix=API_PREFIX)

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "app": health_router.APP_NAME,
            "version": health_router.APP_VERSION,
            "phase": health_router.BUILD_PHASE,
            "docs": "/docs" if not settings.is_prod else None,
            "health": f"{API_PREFIX}/health",
        }

    # Kubernetes/uptime-probe style alias, no prefix and no dependencies.
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    # The engine skips datasets in an archived domain. It cannot read domain
    # status itself — data_access sits at the bottom of the import order — so
    # the answer is handed down from here, once.
    from backend.services import domain_status

    domain_status.install()

    logger.info("CreditProbe API ready (env=%s, cors=%s)", settings.env, list(settings.cors_origins))
    return app


app = create_app()
