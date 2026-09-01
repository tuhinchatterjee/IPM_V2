"""
Ask CreditProbe — the conversational surface, and controlled Trace modification.

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

from backend.analyst import classify
from backend.analyst import cost as ai_cost
from backend.api.permissions import Principal, RequireAdmin, RequireAnalyst
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
    investigation_id: int | None = None
    persist: bool = True
    # Set when the user has answered a period clarification. Two real reporting
    # period labels; anything else is rejected by the analysis contract rather
    # than interpreted here.
    from_period: str | None = Field(default=None, max_length=64)
    to_period: str | None = Field(default=None, max_length=64)
    #: §5. The user's reply to a clarification the analyst asked, carried back
    #: so the SAME investigation continues rather than a new one starting. The
    #: resolved assumption is part of the run key, so "yes, the 12-month PD"
    #: and "no, the movement since last quarter" are different answers to the
    #: same words and neither is served from the other's cache entry.
    clarification: str | None = Field(default=None, max_length=2000)


class ModifyIn(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    version: int | None = Field(
        default=None,
        description="Version to modify. Defaults to the most recent.",
    )


# ------------------------------------------------------------------- context


@router.get("/mode", summary="How questions are currently planned")
def mode() -> dict:
    """How CreditProbe is answering questions, said plainly.

    With no provider key this reports LIMITED OFFLINE MODE and lists what is
    constrained. The product must not present a deterministic semantic planner
    as full natural-language understanding — that is the specific dishonesty
    that let six questions in a row come back confidently wrong.
    """
    from backend.orchestration.orchestrator import mode as orchestrator_mode

    vocab = get_vocabulary()
    return {
        **orchestrator_mode(),
        "analysis_count": len(vocab.analyses),
        "supported_modifications": modification_service.SUPPORTED_OPERATIONS,
    }


# The questions offered on the Cockpit. Each is one CreditProbe can genuinely answer,
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


@router.get("/suggestions", summary="Questions CreditProbe can answer today")
def suggestions() -> dict:
    """What to ask when nothing has been asked yet.

    Built from the catalogue that is actually loaded, so an installation with
    different data gets different suggestions and a demonstration never opens
    with a question about a dataset nobody has. The registered starters stand
    behind that: they are gated on the analyses this build carries, so a
    suggestion never names a method that is not there.
    """
    from backend.orchestration import suggestions as sg
    from backend.orchestration.context import retrieve

    registry = get_registry()
    available = set(registry.ids())
    starters = [{"question": q["question"], "note": q["note"]}
                for q in STARTER_QUESTIONS if q["needs"] in available]

    try:
        from_catalogue = [{"question": q, "note": "From the governed catalogue"}
                          for q in sg.opening(retrieve(""))]
    except Exception:  # noqa: BLE001 - an empty composer is not a failure
        logger.exception("Opening suggestions could not be built")
        from_catalogue = []

    seen: set[str] = set()
    questions: list[dict[str, str]] = []
    for entry in [*from_catalogue, *starters]:
        text = entry["question"].strip().lower()
        if text and text not in seen:
            seen.add(text)
            questions.append(entry)
    return {"questions": questions[:6]}


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


@router.get("/posture", summary="What answers questions in this deployment")
def posture() -> dict:
    """Which path is primary here, and what it is bounded by. §2.

    Named `posture` rather than `mode` because `/ask/mode` already describes
    the PROVIDER's state and this describes the ARCHITECTURE's: which of the
    two paths answers first, how many governed tools it can reach, and how
    many steps it is allowed.
    """
    from backend.analyst import route as analyst_route

    return analyst_route.posture()


@router.post("/investigate", summary="Investigate a question as an analyst")
def investigate(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """The analyst path on its own. §2.

    The model receives the question in the user's own words, inspects the
    governed catalogue, calls governed tools and answers from what came back.
    Every figure is grounded against the evidence before it is returned.

    Separate from POST /ask so that the investigation's own shape — its steps,
    its evidence ledger, its run key — can be read whole, by the Trace and by
    the acceptance runs, without being folded into the deterministic result's
    shape first.
    """
    from backend.analyst import route as analyst_route

    reading = classify.read(payload.question)
    with ai_cost.measuring(payload.question,
                           question_class=reading.question_class,
                           why=reading.why):
        return analyst_route.answer(
            payload.question, principal,
            period=payload.to_period or "",
            clarification=payload.clarification or "")


@router.get("/cost", summary="What recent questions cost")
def cost_trace(limit: int = 50,
               principal: Principal = RequireAdmin) -> dict:
    """The cost trace. R2 §16.

    Per question: how many model calls it took, which models served them, how
    many tokens went in and out, how much of the input arrived from the
    provider's cache, how much of it was catalogue and how much was gathered
    evidence, how many tool calls it made and how many of those repeated one
    already made, and how long it took.

    Administrator-only, and it carries no prompt text, no tool arguments and
    no borrower identifiers — only sizes, counts and model ids. What it is for
    is answering "where is the money going", which is a question about the
    architecture rather than about anybody's book.
    """
    del principal
    trace = ai_cost.trace()
    return {"summary": trace.summary(),
            "questions": [m.to_dict(models=True)
                          for m in trace.recent(
                              max(1, min(limit, ai_cost.HISTORY)))]}


@router.post("", summary="Ask CreditProbe a question")
def ask(payload: AskIn, principal: Principal = RequireAnalyst) -> dict:
    """Plan, execute and narrate one investigation.

    §2: when an intelligence provider is configured the ANALYST answers, and
    the governed semantic reader is the fallback. When one is not — which on a
    bank's own network may be the only permitted arrangement — the reader is
    the whole path, exactly as before.

    The deterministic result is returned either way, because it carries the
    table, the plan and the Trace that the analyst's prose describes. What the
    analyst adds is the investigation: which tools it called, what came back,
    and the reading of it. Both are in the response, so no existing consumer
    has to change to keep working and a new one can use either.
    """
    reading = classify.read(payload.question)
    with ai_cost.measuring(payload.question,
                           question_class=reading.question_class,
                           why=reading.why) as meter:
        body = _ask(payload, principal)
    body["cost"] = meter.to_dict()
    return body


def _ask(payload: AskIn, principal: Principal) -> dict[str, Any]:
    try:
        period = (
            (payload.from_period, payload.to_period)
            if payload.from_period and payload.to_period else None
        )
        investigation = run_investigation(
            payload.question,
            user_id=principal.user_id,
            project_id=payload.project_id,
            investigation_id=payload.investigation_id,
            persist=payload.persist,
            period=period,
        )
    except PlanRejected as e:  # pragma: no cover - run_investigation returns instead
        raise HTTPException(status_code=422,
                            detail={"error": "plan_rejected", "message": str(e),
                                    "reasons": e.reasons}) from e
    body = investigation.to_dict()
    # Belt and braces, and both are load-bearing. `_analyst_view` catches what
    # the analyst can throw; this catches what `_analyst_view` itself can —
    # an import failure, a missing module in a partial deployment. §9: a
    # failure in one path is not a failure of the product, and the
    # deterministic answer above is already computed and correct.
    try:
        body["analyst"] = _analyst_view(payload, principal)
    except Exception as e:  # noqa: BLE001 - the deterministic answer stands
        logger.warning("The analyst view could not be built: %s", e)
        body["analyst"] = {"path": "deterministic", "analyst_available": False,
                           "why": "the governed semantic reader answered"}
    return body


def _analyst_view(payload: AskIn, principal: Principal) -> dict[str, Any]:
    """The analyst's investigation of the same question, when one is possible.

    Never raises. An analyst that cannot run must not take the deterministic
    answer down with it — §9's whole point is that a failure in one path is
    not a failure of the product.
    """
    from backend.analyst import route as analyst_route

    if not analyst_route.available():
        return {"path": analyst_route.DETERMINISTIC,
                "analyst_available": False,
                "why": ("no intelligence provider is configured, so the "
                        "governed semantic reader answered")}
    try:
        return analyst_route.answer(
            payload.question, principal,
            period=payload.to_period or "",
            clarification=payload.clarification or "")
    except Exception as e:  # noqa: BLE001 - the deterministic answer stands
        logger.warning("The analyst could not run alongside /ask: %s", e)
        return {"path": analyst_route.DETERMINISTIC,
                "analyst_available": True,
                "why": "the analyst did not complete; the reader answered"}


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
                    "message": "This trace was recorded before CreditProbe stored the plan behind "
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
