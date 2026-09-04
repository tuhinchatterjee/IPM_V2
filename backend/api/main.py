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
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import auth as auth_router
from backend.api.routers import agentic as agentic_router
from backend.api.routers import ask as ask_router
from backend.api.routers import assurance as assurance_router
from backend.api.routers import brain as brain_router
from backend.api.routers import cases as cases_router
from backend.api.routers import (
    continuous_learning as continuous_learning_router,
)
from backend.api.routers import corporate as corporate_router
from backend.api.routers import data_builder as data_builder_router
from backend.api.routers import domain_intelligence as domain_intelligence_router
from backend.api.routers import early_warning as early_warning_router
from backend.api.routers import engine as engine_router
from backend.api.routers import exports as exports_router
from backend.api.routers import feedback as feedback_router
from backend.api.routers import health as health_router
from backend.api.routers import hierarchy as hierarchy_router
from backend.api.routers import intelligence as intelligence_router
from backend.api.routers import learning as learning_router
from backend.api.routers import lenses as lenses_router
from backend.api.routers import messages as messages_router
from backend.api.routers import metadata as metadata_router
from backend.api.routers import metrics as metrics_router
from backend.api.routers import planner as planner_router
from backend.api.routers import preferences as preferences_router
from backend.api.routers import regulatory as regulatory_router
from backend.api.routers import (
    regulatory_intelligence as regulatory_intelligence_router,
)
from backend.api.routers import (
    scorecard as scorecard_router,
)
from backend.api.routers import studio as studio_router
from backend.api.routers import users as users_router
from backend.api.routers import validation as validation_router
from backend.api.routers import whatif as whatif_router
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
        # A browser hides every response header from cross-origin JavaScript
        # unless the server names it here — `allow_headers` governs the REQUEST,
        # not the response. Without this the workbook downloads reach the
        # browser with the right bytes and no name: `Content-Disposition` is
        # unreadable, so the interface falls back to a generic filename and the
        # governed one the server carefully sanitised never lands on the laptop.
        expose_headers=[
            "Content-Disposition",
            "Content-Length",
            "X-CreditProbe-Run",
            "X-CreditProbe-Trace-Version",
            "X-CreditProbe-Rows",
            "X-Request-ID",
        ],
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

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        """A status a route raised deliberately, said in words. §9.

        The house convention is `HTTPException(status, detail={"error": ...,
        "message": ...})`, and the browser client reads `detail` when it is an
        OBJECT. Most routes follow it. The ones that do not — a bare
        `detail="..."` string, and FastAPI's own defaults for 401, 404 and a
        method mismatch — produced `{"detail": "Not Found"}`, the client found
        no `message`, and it fell back to printing the transport:

            Request failed with status 500.

        That sentence reached a credit officer on a real acceptance run. So
        this handler does one narrow thing: it leaves a well-formed detail
        object alone, and gives every other shape the same object, with a
        sentence written for a person. It never invents a message over one a
        route wrote, except at 5xx — where the text is as likely to have come
        from a driver as from a person, and §9 puts that in the log instead.
        """
        from backend.api import failures

        request_id = getattr(request.state, "request_id", "unknown")
        status_code = int(getattr(exc, "status_code", 500) or 500)
        detail = exc.detail

        if status_code >= 500:
            logger.error("HTTP %s on %s (request %s): %s",
                         status_code, request.url.path, request_id, detail)

        if isinstance(detail, dict):
            body = dict(detail)
            body.setdefault("error", f"http_{status_code}")
            written = str(body.get("message") or "")
            if (status_code >= 500 or not written
                    or failures.leaks(written)):
                body["message"] = failures.for_status(status_code)
        else:
            raw = detail if isinstance(detail, str) else ""
            body = {"error": f"http_{status_code}",
                    "message": failures.for_status(status_code, raw)}

        body.setdefault("status", status_code)
        body["request_id"] = request_id
        body["correlation_id"] = request_id
        return JSONResponse(
            status_code=status_code,
            headers=getattr(exc, "headers", None) or None,
            content={"detail": body},
        )

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(request: Request, exc: RequestValidationError):
        """A malformed request body, in the same envelope. §9.

        Pydantic's own body is a LIST of dicts naming field locations and
        internal type codes. It is exactly the engineering detail §9 says
        belongs in the log, and it reached the browser — where the client,
        finding a list rather than an object, printed the status instead.

        The field NAMES stay: refusing to leak internals is not a licence to
        make somebody guess which value was wrong.
        """
        from backend.api import failures

        request_id = getattr(request.state, "request_id", "unknown")
        logger.info("Invalid request on %s (request %s): %s",
                    request.url.path, request_id, exc.errors())
        fields = sorted({
            str(part) for error in exc.errors()
            for part in (error.get("loc") or ())
            if isinstance(part, str) and part not in ("body", "query", "path")
        })
        message = failures.for_status(422)
        if fields:
            message += " Check: " + ", ".join(fields[:6]) + "."
        return JSONResponse(
            status_code=422,
            content={"detail": {"error": "invalid_request", "message": message,
                                "fields": fields[:12], "status": 422,
                                "request_id": request_id,
                                "correlation_id": request_id}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak a stack trace to the browser; log it in full instead.
        #
        # P0.10: categorised rather than reported as one anonymous 500. "Something
        # went wrong on the server" was shown for a missing dataset, an
        # unreachable provider, a permission refusal and — during Phase 0 — a
        # stopped database, which is not a fault in CreditProbe at all. Each of
        # those is a different thing for the reader to do.
        from backend.api import failures

        request_id = getattr(request.state, "request_id", "unknown")
        failure = failures.of(exc, request_id)
        logger.exception(
            "%s failure on %s (request %s): %s",
            failure.category, request.url.path, request_id, type(exc).__name__)
        # `error` and `message` appear BOTH at the top level and inside
        # `detail`. The house convention for a deliberate refusal is
        # `HTTPException(status, detail={"error", "message"})`, so the browser
        # client reads `detail` when it is an object; this handler's own shape
        # is flat. Two shapes meant two readers, and the second one — the
        # fallback for "neither" — is what printed "Request failed with status
        # 500." Carrying the pair in both places costs a few bytes and leaves
        # exactly one way to read an error.
        return JSONResponse(
            status_code=failure.status,
            content=ErrorResponse(
                error=failure.category.lower(),
                message=failure.message,
                detail={"error": failure.category.lower(),
                        "message": failure.message,
                        "request_id": request_id,
                        "correlation_id": request_id,
                        "status": failure.status,
                        "category": failure.category},
            ).model_dump(),
        )

    # ---------------------------------------------------------------- routes

    app.include_router(auth_router.router, prefix=API_PREFIX)
    app.include_router(health_router.router, prefix=API_PREFIX)
    app.include_router(users_router.router, prefix=API_PREFIX)
    app.include_router(preferences_router.router, prefix=API_PREFIX)
    app.include_router(messages_router.router, prefix=API_PREFIX)
    app.include_router(data_builder_router.router, prefix=API_PREFIX)
    app.include_router(metadata_router.router, prefix=API_PREFIX)
    app.include_router(engine_router.engine_router, prefix=API_PREFIX)
    app.include_router(engine_router.trace_router, prefix=API_PREFIX)
    app.include_router(ask_router.router, prefix=API_PREFIX)
    app.include_router(ask_router.trace_edit_router, prefix=API_PREFIX)
    app.include_router(early_warning_router.router, prefix=API_PREFIX)
    app.include_router(domain_intelligence_router.router,
                       prefix=API_PREFIX)
    # The governed agentic layer: runs, the live officer indicator,
    # the registry, schedules, policies, approvals — and Risk Cases,
    # which the Cockpit's Requires Attention reads.
    app.include_router(agentic_router.router, prefix=API_PREFIX)
    app.include_router(assurance_router.router, prefix=API_PREFIX)
    app.include_router(assurance_router.dimensions_router,
                       prefix=API_PREFIX)
    app.include_router(cases_router.router, prefix=API_PREFIX)
    # Answer feedback: §148 requires it on every response, so the POST
    # is open to every signed-in role. Reading the queue and
    # adjudicating are not.
    app.include_router(feedback_router.router, prefix=API_PREFIX)
    app.include_router(regulatory_router.router, prefix=API_PREFIX)
    # Analysis Studio → Regulatory Intelligence. §27 keeps this separate
    # from the document library above: a source circular and a certified
    # method are not the same kind of object, and one screen for both is how
    # a bank ends up telling its regulator that uploading a PDF was an
    # implementation.
    app.include_router(regulatory_intelligence_router.router,
                       prefix=API_PREFIX)
    app.include_router(learning_router.router, prefix=API_PREFIX)
    # Continuous Learning: what has been captured, and — separately, and
    # never added to it — what measurably changed. Deterministic and cheap
    # to open, because a screen that costs money to look at is a screen
    # nobody looks at.
    app.include_router(continuous_learning_router.router, prefix=API_PREFIX)
    app.include_router(corporate_router.router, prefix=API_PREFIX)
    app.include_router(scorecard_router.router, prefix=API_PREFIX)
    app.include_router(regulatory_router.corpus_router,
                       prefix=API_PREFIX)
    app.include_router(hierarchy_router.projects_router, prefix=API_PREFIX)
    app.include_router(hierarchy_router.threads_router, prefix=API_PREFIX)
    app.include_router(hierarchy_router.analyses_router, prefix=API_PREFIX)
    app.include_router(lenses_router.router, prefix=API_PREFIX)
    app.include_router(metrics_router.router, prefix=API_PREFIX)
    app.include_router(whatif_router.router, prefix=API_PREFIX)
    app.include_router(studio_router.router, prefix=API_PREFIX)
    # The AI Intelligence Studio, on /intelligence. Distinct from the four
    # borrower-level domain readings on /domain-intelligence above: this one
    # is about how the product is performing, that one about a name.
    app.include_router(intelligence_router.router, prefix=API_PREFIX)
    # The Brain Center: the Learning Ledger, exports, quarantine, the Lift
    # Lab, installations and the trusted signer registry. Reading is open to
    # the Studio's audience; activating a Brain is an administrator's alone.
    app.include_router(brain_router.router, prefix=API_PREFIX)
    # Delivery projects: the plan, who owes what, and when it is late.
    # Distinct from hierarchy_router's /projects, which is the analytical
    # workspace a piece of credit work lives in.
    app.include_router(planner_router.router, prefix=API_PREFIX)
    app.include_router(workspace_router.router, prefix=API_PREFIX)
    app.include_router(validation_router.router, prefix=API_PREFIX)
    app.include_router(exports_router.runs_router, prefix=API_PREFIX)
    app.include_router(exports_router.trace_router, prefix=API_PREFIX)

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
