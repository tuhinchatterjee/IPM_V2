"""
Health and system-status endpoints.

`/api/v1/health` is what the front end's status indicator polls. It is
deliberately honest and granular: it reports each dependency separately and never
claims a component is fine when it has not been checked.

Design decision worth stating: a missing dependency is reported, not fatal. The
API starts and serves even when PostgreSQL has not been configured or the data
lake has not been built, and says so precisely. For a non-developer setting this
up for the first time, "PostgreSQL is not configured — set DATABASE_URL in .env"
on a working screen is far more useful than a server that refuses to boot.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.api.schemas import (
    AnalysisSummary,
    AnalyticalDatasetSummary,
    CatalogResponse,
    ComponentHealth,
    EngineLibraryResponse,
    HealthResponse,
)
from backend.build_info import build_info, started_at
from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

APP_NAME = "CreditProbe AI — Credit Portfolio Intelligence"
#: Read from the build rather than typed here, so it cannot drift from what is
#: actually running. See backend/build_info.
APP_VERSION = build_info().version
BUILD_PHASE = "Credit intelligence"

# Worst-first, so the overall status is the worst component present.
_SEVERITY = {"unavailable": 3, "not_configured": 2, "degraded": 2, "empty": 1, "ok": 0}


def _check_analytical_store() -> ComponentHealth:
    """DuckDB over the Parquet analytics layer."""
    try:
        from backend.data_access import get_data_source

        health = get_data_source().health()
        count = health.get("dataset_count", 0)
        if health.get("status") == "error":
            return ComponentHealth(
                name="analytical_store", status="unavailable",
                detail=health.get("error", "The analytical store could not be queried."),
                data=health,
            )
        if count == 0:
            return ComponentHealth(
                name="analytical_store", status="empty",
                detail="No analytical datasets found. Run: python scripts/generate_saudi_universe.py",
                data=health,
            )
        return ComponentHealth(
            name="analytical_store", status="ok",
            detail=f"DuckDB serving {count} Parquet dataset(s).", data=health,
        )
    except Exception as e:
        logger.exception("Analytical store health check failed")
        return ComponentHealth(
            name="analytical_store", status="unavailable",
            detail=f"Could not reach the analytical store: {e}",
        )


def _check_catalog() -> ComponentHealth:
    """The governed data dictionary."""
    try:
        from backend.data_access import get_catalog

        catalog = get_catalog()
        if len(catalog) == 0:
            return ComponentHealth(
                name="data_catalog", status="empty",
                detail="No governed datasets defined. Run: python scripts/generate_saudi_universe.py",
            )
        fields = sum(len(d.fields) for d in catalog.all())
        return ComponentHealth(
            name="data_catalog", status="ok",
            detail=f"{len(catalog)} governed dataset(s), {fields} defined fields.",
            data={"datasets": catalog.names(), "field_count": fields},
        )
    except Exception as e:
        logger.exception("Catalog health check failed")
        return ComponentHealth(name="data_catalog", status="unavailable", detail=str(e))


def _check_database() -> ComponentHealth:
    """PostgreSQL — the application, governance and metadata store."""
    if not settings.has_database:
        return ComponentHealth(
            name="postgresql", status="not_configured",
            detail="DATABASE_URL is not set. Start the database with: docker compose up -d db",
        )
    try:
        from sqlalchemy import text

        from backend.db.engine import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ComponentHealth(name="postgresql", status="ok", detail="Connected.")
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return ComponentHealth(
            name="postgresql", status="unavailable",
            detail=f"Configured but unreachable: {e}",
        )


def _check_engine() -> ComponentHealth:
    """The analytical function registry."""
    try:
        from backend.engine.registry import get_registry

        registry = get_registry()
        summary = registry.summary()
        if summary["total"] == 0:
            return ComponentHealth(
                name="ipm_engine", status="empty",
                detail="No analytical functions registered yet (they arrive in Phase 2).",
                data=summary,
            )
        return ComponentHealth(
            name="ipm_engine", status="ok",
            detail=f"{summary['total']} registered analyses.", data=summary,
        )
    except Exception as e:
        logger.exception("Engine registry health check failed")
        return ComponentHealth(name="ipm_engine", status="unavailable", detail=str(e))


def _check_ai() -> ComponentHealth:
    """The AI provider, reported from calls actually made.

    A key alone reports `not_configured`-adjacent honesty rather than health:
    CONFIGURED means "reachable, unproven". Only CONNECTED — a real structured
    response — reports ok.
    """
    try:
        from backend.llm import health as ai_health
        from backend.llm import telemetry

        observed = ai_health()
        status = {
            telemetry.CONNECTED: "ok",
            telemetry.CONFIGURED: "degraded",
            telemetry.DEGRADED: "degraded",
            telemetry.OFFLINE: "not_configured",
        }.get(observed["state"], "degraded")
        return ComponentHealth(name="ai_provider", status=status,
                               detail=observed["detail"], data=observed)
    except Exception as e:  # noqa: BLE001 - health must never raise
        logger.exception("AI provider health check failed")
        return ComponentHealth(name="ai_provider", status="unavailable",
                               detail=str(e))


@router.get("/build", summary="Which build is running")
def build() -> dict:
    """The commit, the image and whether they agree.

    Exists because "is the container running the code I just pulled?" was not
    answerable during a production incident, and the answer to that question
    changes where you look next.
    """
    from backend.llm import health as ai_health

    info = build_info()
    return {
        "app": APP_NAME,
        "environment": settings.env,
        "started_at": started_at(),
        "build": info.to_dict(),
        "ai": ai_health(),
    }


@router.get("/health", response_model=HealthResponse, summary="System health")
def health() -> HealthResponse:
    components = [_check_database(), _check_analytical_store(), _check_catalog(),
                  _check_engine(), _check_ai()]
    worst = max(_SEVERITY.get(c.status, 0) for c in components) if components else 0
    # "empty" is an expected Phase 1 state, not a fault — a system with no engine
    # functions registered yet is working exactly as designed.
    overall = "ok" if worst <= 1 else ("degraded" if worst == 2 else "unavailable")
    return HealthResponse(
        status=overall,
        app=APP_NAME,
        version=APP_VERSION,
        environment=settings.env,
        phase=BUILD_PHASE,
        components=components,
    )


@router.get("/catalog", response_model=CatalogResponse, summary="Governed data catalogue")
def catalog() -> CatalogResponse:
    """The Data Dictionary — what Data Builder renders in Phase 5."""
    from backend.data_access import get_catalog, get_data_source

    cat = get_catalog()
    source = get_data_source()
    available = set(source.datasets())

    datasets = [
        AnalyticalDatasetSummary(
            name=d.name,
            business_name=d.business_name,
            domain=d.domain,
            grain=d.grain,
            field_count=len(d.fields),
            periods=source.periods(d.name) if d.name in available else [],
            is_synthetic=d.is_synthetic,
        )
        for d in cat.all()
    ]
    return CatalogResponse(
        dataset_count=len(cat),
        field_count=sum(len(d.fields) for d in cat.all()),
        domains=cat.domains(),
        datasets=datasets,
    )


@router.get("/engine/library", response_model=EngineLibraryResponse, summary="Analysis Library")
def engine_library() -> EngineLibraryResponse:
    """Registered analytical capabilities — the Engine Builder Analysis Library.

    Empty in Phase 1 by design; Phase 2 registers the ten certified analyses.
    """
    from backend.engine.registry import get_registry

    registry = get_registry()
    analyses = [
        AnalysisSummary(
            id=c.id,
            name=c.name,
            description=c.description,
            category=c.category.value,
            version=c.version,
            owner=c.owner,
            certification=c.certification.value,
            is_certified=c.is_certified,
            is_runnable=c.is_runnable,
        )
        for c in registry.contracts()
    ]
    return EngineLibraryResponse(
        total=len(analyses),
        certified=sum(1 for a in analyses if a.is_certified),
        analyses=analyses,
    )
