"""
Ask IPM — the conversational surface, and controlled Trace modification.

    GET  /ask/mode                        how questions are being planned
    GET  /ask/suggestions                 starting questions, built from the library
    GET  /ask/briefing                    the Cockpit's portfolio briefing
    GET  /ask/recent                      the questions asked most recently
    POST /ask                             answer a question
    GET  /trace/{run_id}/versions         every stored version of one investigation
    POST /trace/{run_id}/modify/preview   what a change would do — runs nothing
    POST /trace/{run_id}/modify/apply     run it, into a NEW version

Two things this surface deliberately does not accept: SQL, and code. The only
free text it takes is a question or a modification request, and both are read
into a validated plan before anything executes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.permissions import Principal, RequireAnalyst
from backend.engine.registry import get_registry
from backend.engine.runner import run_analysis
from backend.orchestration import modification as modification_service
from backend.orchestration import store
from backend.orchestration.executor import STAGES, run_investigation
from backend.orchestration.planner import planner_mode
from backend.orchestration.schema import PlanRejected
from backend.orchestration.vocabulary import get_vocabulary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])
trace_edit_router = APIRouter(prefix="/trace", tags=["trace"])

MAX_QUESTION_CHARS = 500


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    project_id: int | None = None
    chat_id: int | None = None
    persist: bool = True


class ModifyIn(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    version: int | None = Field(
        default=None,
        description="Version to modify. Defaults to the most recent.",
    )


# ------------------------------------------------------------------- context


@router.get("/mode", summary="How questions are currently planned")
def mode() -> dict:
    vocab = get_vocabulary()
    return {
        **planner_mode(),
        "stages": STAGES,
        "analysis_count": len(vocab.analyses),
        "periods": vocab.periods,
        "latest_period": vocab.latest,
        "dimensions": {k: len(v) for k, v in vocab.dimensions.items()},
        "supported_modifications": modification_service.SUPPORTED_OPERATIONS,
    }


# The questions offered on the Cockpit. Each is one IPM can genuinely answer,
# which is checked below against the live registry rather than assumed.
STARTER_QUESTIONS = [
    {"question": "What deteriorated this period?", "needs": "portfolio_summary",
     "note": "The standard opening review"},
    {"question": "Why has Stage 2 increased?", "needs": "stage_migration",
     "note": "Migration, drivers and impairment consequence"},
    {"question": "Which sectors deteriorated the most?", "needs": "ecl_movement",
     "note": "Attribution by sector"},
    {"question": "Show me the top ten deteriorating borrowers.",
     "needs": "top_deteriorating_borrowers", "note": "Names, with reasons"},
    {"question": "Show me the rating transition matrix.",
     "needs": "rating_transition_matrix", "note": "Empirical transitions"},
    {"question": "Stress the Real Estate portfolio.", "needs": "stress_scenario_basic",
     "note": "Downturn sensitivity on one sector"},
    {"question": "How has ECL changed?", "needs": "ecl_movement",
     "note": "Impairment bridge"},
    {"question": "Where is the book most concentrated?", "needs": "sector_concentration",
     "note": "Concentration and its quality"},
]


@router.get("/suggestions", summary="Questions IPM can answer today")
def suggestions() -> dict:
    registry = get_registry()
    available = set(registry.ids())
    return {
        "questions": [
            {"question": q["question"], "note": q["note"]}
            for q in STARTER_QUESTIONS
            if q["needs"] in available
        ]
    }


@router.get("/recent", summary="Recently asked questions")
def recent(limit: int = 8) -> dict:
    return {"investigations": store.recent_investigations(max(1, min(50, limit)))}


@router.get("/briefing", summary="The Cockpit portfolio briefing")
def briefing() -> dict:
    """Headline position and the deterioration signals worth opening with.

    Both come from executing registered analyses, not from a stored snapshot: the
    briefing is as live as any other answer, and carries the run ids so each
    figure on it has a working Trace button.
    """
    out: dict[str, Any] = {"period": None, "summary": None, "attention": None,
                           "trend": None, "errors": []}

    try:
        summary = run_analysis("portfolio_summary",
                               params={"period": "latest", "compare_period": "previous"})
        out["summary"] = summary.to_dict()
        out["period"] = (summary.result.values.get("period") if summary.result else None)
    except Exception as e:
        logger.warning("Briefing summary failed: %s", e)
        out["errors"].append(f"Portfolio summary: {e}")

    try:
        attention = run_analysis("top_deteriorating_borrowers",
                                 params={"from_period": "previous", "to_period": "latest",
                                         "top_n": 5})
        out["attention"] = attention.to_dict()
    except Exception as e:
        logger.warning("Briefing attention failed: %s", e)
        out["errors"].append(f"Deterioration signals: {e}")

    try:
        trend = run_analysis("portfolio_trend", params={})
        out["trend"] = trend.to_dict()
    except Exception as e:
        logger.warning("Briefing trend failed: %s", e)
        out["errors"].append(f"Trend: {e}")

    return out


# ----------------------------------------------------------------------- ask


@router.post("", summary="Ask IPM a question")
def ask(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """Plan, execute and narrate one investigation."""
    try:
        investigation = run_investigation(
            payload.question,
            user_id=principal.user_id,
            project_id=payload.project_id,
            chat_id=payload.chat_id,
            persist=payload.persist,
        )
    except PlanRejected as e:  # pragma: no cover - run_investigation returns instead
        raise HTTPException(status_code=422,
                            detail={"error": "plan_rejected", "message": str(e),
                                    "reasons": e.reasons}) from e
    return investigation.to_dict()


# ------------------------------------------------------- trace modification


def _load(run_id: int, version: int | None) -> dict[str, Any]:
    try:
        return store.load_version(run_id, version)
    except store.InvestigationNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"error": "trace_not_found", "message": str(e)}) from e


@trace_edit_router.get("/{run_id}/versions", summary="Every version of one investigation")
def versions(run_id: int) -> dict:
    payload = _load(run_id, None)
    return {
        "analysis_run_id": run_id,
        "question": payload["question"],
        "versions": payload["available_versions"],
        "current": payload["version"],
        "modifications": store.list_modifications(run_id),
        "supported": modification_service.SUPPORTED_OPERATIONS,
    }


@trace_edit_router.post("/{run_id}/modify/preview",
                        summary="What a change would do — nothing is executed")
def preview_modification(run_id: int, payload: ModifyIn) -> dict:
    stored = _load(run_id, payload.version)
    plan = store.plan_of(stored)
    if not plan.steps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_modifiable",
                    "message": "This trace was recorded before IPM stored the plan behind "
                               "it, so it cannot be modified. Re-run the analysis to get a "
                               "modifiable version."},
        )
    change = modification_service.preview(payload.request, plan, stored["graph"])
    return {
        "analysis_run_id": run_id,
        "from_version": stored["version"],
        **change.to_dict(),
    }


@trace_edit_router.post("/{run_id}/modify/apply",
                        summary="Apply a change into a NEW version")
def apply_modification(run_id: int, payload: ModifyIn,
                       principal: Principal = RequireAnalyst) -> dict:
    """Re-run the affected steps and store the result as a new version.

    The version being modified is never altered. Steps whose analysis, parameters
    and filters are unchanged reuse their recorded results and are marked as such.
    """
    stored = _load(run_id, payload.version)
    plan = store.plan_of(stored)
    if not plan.steps:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_modifiable",
                    "message": "This trace has no stored plan and cannot be modified."},
        )

    change = modification_service.preview(payload.request, plan, stored["graph"])
    if not change.applicable:
        raise HTTPException(
            status_code=422,
            detail={"error": "modification_not_applicable",
                    "message": change.description,
                    "rejected": change.rejected,
                    "supported": change.supported},
        )

    try:
        investigation = modification_service.apply_modification(
            plan, store.steps_of(stored), change, user_id=principal.user_id,
        )
    except PlanRejected as e:
        raise HTTPException(status_code=422,
                            detail={"error": "plan_rejected", "message": str(e),
                                    "reasons": e.reasons}) from e

    hash_diff = investigation.graph.diff_hashes(stored["node_hashes"])
    try:
        saved = store.save_version(
            run_id, from_version_id=stored["version_id"], investigation=investigation,
            request_text=payload.request,
            change_payload={"operation": change.operation.to_dict() if change.operation else {},
                            "affected_nodes": change.affected_nodes,
                            "hash_diff": hash_diff},
            user_id=principal.user_id,
        )
    except store.InvestigationNotFound as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"error": "not_stored", "message": str(e)}) from e

    body = investigation.to_dict()
    body.update({
        "analysis_run_id": run_id,
        "version": saved["version"],
        "version_label": saved["label"],
        "from_version": stored["version"],
        "request": payload.request,
        "change": change.to_dict(),
        "hash_diff": hash_diff,
        "available_versions": store.load_version(run_id)["available_versions"],
    })
    return body


@trace_edit_router.get("/{run_id}/investigation",
                       summary="A stored investigation, with its narrative and steps")
def investigation(run_id: int, version: int | None = None) -> dict:
    payload = _load(run_id, version)
    return {**payload, "stages": STAGES, "mode": planner_mode()}


__all__ = ["router", "trace_edit_router"]
