"""
Downloading an analysis as a workbook.

    GET  /analysis-runs/{run_id}/export/results.xlsx          the results workbook
    GET  /trace/{run_id}/export/calculation-pack.xlsx         the full pack
    GET  /analysis-runs/{run_id}/export/availability          what this user may have
    GET  /analysis-runs/{run_id}/export/history               who has downloaded it

Two downloads, deliberately separate. A single "Export" button that produced
different files depending on where it was pressed would be the worst of both:
the person who wanted the numbers gets a twenty-sheet audit pack, and the
reviewer who wanted the evidence gets a table.

This router is thin on purpose. Everything that decides anything lives in
`backend.exports.service`; here we turn an `ExportError` into a status code and
a body, and set the headers a browser needs to save a file.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.api.permissions import Principal, current_principal
from backend.exports import audit, authorize, service
from backend.exports.contract import (
    CALCULATION_PACK,
    RESULTS,
    XLSX_MIME,
    ExportError,
)

logger = logging.getLogger(__name__)

runs_router = APIRouter(prefix="/analysis-runs", tags=["exports"])
trace_router = APIRouter(prefix="/trace", tags=["exports"])


def _serve(run_id: int, *, kind: str, principal: Principal,
           version: int | None) -> Response:
    """Generate, audit and return one workbook as a download."""
    try:
        served = service.export(
            run_id, kind=kind, principal=principal, version=version,
            user_name=_name_of(principal),
        )
    except ExportError as e:
        raise HTTPException(
            status_code=e.status,
            detail={"error": e.code, "message": e.message,
                    "run_id": run_id, "kind": kind},
        ) from e

    workbook = served.workbook
    return Response(
        content=workbook.content,
        media_type=XLSX_MIME,
        headers={
            # RFC 6266: the plain filename for old clients, the UTF-8 form for
            # everyone else. Both are already sanitised by `contract.slug`, so
            # a question title with a slash in it cannot become a path.
            "Content-Disposition": (
                f'attachment; filename="{workbook.filename}"; '
                f"filename*=UTF-8''{workbook.filename}"
            ),
            "Content-Length": str(workbook.size),
            # A workbook is a point-in-time record of a specific Trace version.
            # Caching one and serving it after the analysis is re-run would hand
            # somebody yesterday's numbers under today's filename.
            "Cache-Control": "no-store, max-age=0",
            "X-CreditProbe-Run": str(run_id),
            "X-CreditProbe-Trace-Version": str(
                workbook.manifest.get("trace_version") or ""),
            "X-CreditProbe-Rows": str(workbook.manifest.get("row_count") or 0),
        },
    )


def _name_of(principal: Principal) -> str:
    """The downloader's name, for the workbook's cover.

    Best-effort and cosmetic: a name that cannot be resolved leaves the cover
    saying "user 12" rather than failing an export.
    """
    if principal.user_id is None:
        return ""
    from backend.config import settings

    if not settings.has_database:
        return ""
    try:
        from backend.db.engine import get_session
        from backend.db.models import User

        with get_session() as session:
            user = session.get(User, principal.user_id)
            if user is None:
                return ""
            return f"{user.first_name} {user.last_name}".strip() or user.username
    except Exception as e:  # noqa: BLE001
        logger.info("Could not resolve the downloader's name: %s", e)
        return ""


@runs_router.get(
    "/{run_id}/export/results.xlsx",
    summary="The results workbook for one analysis",
    responses={200: {"content": {XLSX_MIME: {}}}},
)
def results_workbook(
    run_id: int,
    version: int | None = Query(default=None,
                                description="Trace version; the latest if omitted"),
    principal: Principal = Depends(current_principal),
) -> Response:
    """The concise workbook: the answer, the result table and its provenance."""
    return _serve(run_id, kind=RESULTS, principal=principal, version=version)


@trace_router.get(
    "/{run_id}/export/calculation-pack.xlsx",
    summary="The full calculation and validation pack for one analysis",
    responses={200: {"content": {XLSX_MIME: {}}}},
)
def calculation_pack(
    run_id: int,
    version: int | None = Query(default=None,
                                description="Trace version; the latest if omitted"),
    principal: Principal = Depends(current_principal),
) -> Response:
    """The evidence pack: sources, joins, steps, checks, and the final result."""
    return _serve(run_id, kind=CALCULATION_PACK, principal=principal,
                  version=version)


@runs_router.get("/{run_id}/export/availability",
                 summary="Which exports this user may download")
def availability(
    run_id: int,
    principal: Principal = Depends(current_principal),
) -> dict:
    """What the buttons should offer, and what to say where they cannot.

    The interface asks this so a refusal is explained in place rather than
    discovered as a 403 after a click. It is a courtesy, not a control: the
    download endpoints make the same decision for themselves, and a caller who
    skips this one is refused there.
    """
    decisions = {
        RESULTS: authorize.decide(principal, kind=RESULTS, run_id=run_id),
        CALCULATION_PACK: authorize.decide(principal, kind=CALCULATION_PACK,
                                           run_id=run_id),
    }
    return {
        "run_id": run_id,
        "results": {
            "allowed": decisions[RESULTS].allowed,
            "reason": decisions[RESULTS].reason,
            "label": "DOWNLOAD RESULTS",
            "href": f"/api/v1/analysis-runs/{run_id}/export/results.xlsx",
        },
        "calculation_pack": {
            "allowed": decisions[CALCULATION_PACK].allowed,
            "reason": decisions[CALCULATION_PACK].reason,
            "row_level": decisions[CALCULATION_PACK].row_level,
            "label": "DOWNLOAD FULL CALCULATION",
            "href": f"/api/v1/trace/{run_id}/export/calculation-pack.xlsx",
        },
    }


@runs_router.get("/{run_id}/export/history",
                 summary="Who has downloaded this analysis")
def export_history(
    run_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(current_principal),
) -> dict:
    """The download history of one run, for the Analysis audit view.

    Visible to whoever may download the full pack: knowing who else has a copy
    of an analysis is part of the same trust boundary as having one.
    """
    decision = authorize.decide(principal, kind=CALCULATION_PACK, run_id=run_id)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden",
                    "message": "The download history of an analysis is visible "
                               "to those who may download its full calculation "
                               "pack."},
        )
    return {"run_id": run_id, "exports": audit.history(run_id=run_id, limit=limit)}
