"""
Answer feedback, over HTTP. §148-§160.

    §148: "After every CreditProbe response, show a compact feedback
           control."

Why the POST is open to every signed-in role
----------------------------------------------
Because §148 says every response, and the people most likely to notice a
wrong answer are the analysts who read them all day — not the administrators
who read the Studio. A feedback control that only privileged users could use
would collect feedback from the people least exposed to the product.

Reading and adjudicating are a different matter. A list of every complaint is
a map of where CreditProbe is weak, which is authoring-surface information;
and adjudicating changes what the product believes, which is the narrowest
permission there is.

Nothing here changes production
---------------------------------
The POST stores. The triage suggests. Neither promotes anything, updates a
score, or writes a teaching case. §155's loop needs a named reviewer at
ADJUDICATE, and the transition table refuses every path that skips it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.permissions import (
    Principal,
    RequireAdmin,
    RequireAnalyst,
    RequireCommenter,
)
from backend.feedback import components as fc
from backend.feedback import schema as fs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    """§151's fields, as a caller supplies them.

    The context fields are optional in the schema and effectively mandatory
    in practice: without them the item is an opinion rather than a bug
    report, and `reproducible` says so on the way back.
    """

    rating: str = Field(..., description="GOOD or BAD")
    answer_id: str = Field(..., min_length=1)
    reason_codes: list[str] = Field(default_factory=list)
    comment: str = ""
    expected_behavior: str = ""
    selected_fact_ids: list[str] = Field(default_factory=list)
    selected_chart_element: str = ""
    selected_trace_node: str = ""

    message_id: str = ""
    investigation_id: str = ""
    analysis_run_id: str = ""
    trace_id: str = ""
    agentic_run_id: str = ""
    project_id: str = ""
    scope: str = ""
    language: str = "en"


@router.get("/options")
def options(principal: Principal = RequireCommenter) -> dict[str, Any]:
    """What the control offers, so the interface does not hold its own copy.

    Two lists of reasons in two places become two different lists, and the
    one users see will be the stale one.
    """
    return {
        "version": fs.FEEDBACK_VERSION,
        "ratings": list(fs.RATINGS),
        "reasons": {
            fs.GOOD: [{"code": c, "label": fs.LABELS[c]}
                      for c in fs.GOOD_REASONS],
            fs.BAD: [{"code": c, "label": fs.LABELS[c]}
                     for c in fs.BAD_REASONS],
        },
        "acknowledgement": fs.THANKS,
        "bad_reason_encouraged": True,
        "note": ("A reason is strongly encouraged on BAD and not required: "
                 "refusing it loses the signal from the user who is annoyed "
                 "and about to close the tab."),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def leave(body: FeedbackRequest,
          principal: Principal = RequireCommenter) -> dict[str, Any]:
    """Record one piece of feedback. §148.

    Open to every signed-in role including VIEWER, because the people most
    likely to notice a wrong answer are the ones who read answers all day.

    Stores and stops. Nothing here promotes a teaching case, moves a score or
    changes what CreditProbe believes — §155's loop needs a named reviewer,
    and the transition table refuses every path that skips one.
    """
    try:
        item = fs.create(
            rating=body.rating.upper(), answer_id=body.answer_id,
            reasons=body.reason_codes, comment=body.comment,
            expected=body.expected_behavior,
            user_id=principal.user_id,
            message_id=body.message_id,
            investigation_id=body.investigation_id,
            analysis_run_id=body.analysis_run_id,
            trace_id=body.trace_id, agentic_run_id=body.agentic_run_id,
            project_id=body.project_id, scope=body.scope,
            language=body.language,
            selected_fact_ids=body.selected_fact_ids,
            selected_chart_element=body.selected_chart_element,
            selected_trace_node=body.selected_trace_node,
            build_sha=_sha(),
            teaching_release_id=_teaching_release())
    except fs.WouldStoreSecret as leak:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "would_store_secret", "message": str(leak)}
        ) from leak
    except ValueError as bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_feedback", "message": str(bad)}
        ) from bad

    item.feedback_id = uuid.uuid4().hex[:16]
    logger.info("Feedback %s recorded: %s on %s", item.feedback_id,
                item.rating, item.answer_id)

    return {
        "feedback_id": item.feedback_id,
        "status": item.status,
        # §149's exact wording, from the constant. Reviewed, not learned from.
        "acknowledgement": fs.acknowledgement(item.rating),
        "reproducible": item.reproducible,
        "reason_missing": item.reason_missing,
        # The advisory triage, returned so the caller can see it was made and
        # that nothing acted on it.
        "triage": fc.triage(item).to_dict(),
        "changes_production": False,
    }


def _sha() -> str:
    """The build this feedback was left against.

    Without it the item is an opinion. With it somebody can check out the
    same code and reproduce what the user saw, which is the difference
    between feedback and a bug report.
    """
    try:
        from backend.build_info import build_info

        return str(getattr(build_info(), "git_sha", "") or "")
    except Exception:  # pragma: no cover - no build stamp
        return ""


def _teaching_release() -> str:
    try:
        from backend.teaching import release as tr

        return tr.gate(require_release=False).release_id or ""
    except Exception:  # pragma: no cover - no release on disk
        return ""


@router.get("/components")
def components(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§159's components, and the two numbers that never mix.

    Readable by an analyst because "how is CreditProbe performing" is a
    question an analyst is entitled to ask about an answer they were given.
    """
    return {
        "version": fc.COMPONENT_VERSION,
        "components": list(fc.COMPONENTS),
        "states": list(fc.STATES),
        "attribution": {code: list(fc.SUGGESTS[code])
                        for code in sorted(fc.SUGGESTS)},
        "two_numbers": {
            "raw_feedback": ("What users did. Measures who bothered to click "
                             "— overwhelmingly people who were annoyed — and "
                             "agreement, which is not correctness."),
            "validation_score": ("What evaluation established. Derived from "
                                 "versioned case sets, the sealed holdout, "
                                 "critical evaluations and adjudicated "
                                 "feedback regressions."),
            "never_mixed": True,
        },
        "score_moves_only_when": [
            "a versioned case or evaluation set changed",
            "an approved fix was tested",
            "the evaluation completed",
            "the result is tied to a release and build",
            "a named reviewer approved the promotion",
        ],
    }


@router.get("/workflow")
def workflow(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§155's loop, and the transitions it permits.

    Administrator-only: a list of every complaint is a map of where
    CreditProbe is weak, which is authoring-surface information.
    """
    return {
        "version": fs.FEEDBACK_VERSION,
        "statuses": list(fs.STATUSES),
        "transitions": {k: list(v) for k, v in fs.TRANSITIONS.items()},
        "adjudicated_states": sorted(fs.ADJUDICATED_STATES),
        "no_automatic_self_training": True,
        "note": ("Nothing moves from NEW to RELEASED. Every path passes "
                 "through ADJUDICATE, which needs a named reviewer."),
    }


__all__ = ["router"]
