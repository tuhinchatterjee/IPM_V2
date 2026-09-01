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

    # §199. The Assurance Record for this answer learns that somebody
    # disagreed with it — a raw counter and nothing else. There is no code
    # path from here to any check, dimension or status, which is a stronger
    # guarantee that a thumb cannot move a score than a policy would be.
    linked = _note_on_assurance(item)

    return {
        "feedback_id": item.feedback_id,
        "linked_to_assurance_record": linked,
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


def _note_on_assurance(item: Any) -> bool:
    """Increment the raw feedback counter on the answer's record.

    Never raises and never blocks the feedback: an answer whose assurance
    record was never written is still an answer somebody wants to complain
    about.
    """
    try:
        from backend.assurance import store as ast

        return ast.note_feedback(
            item.answer_id,
            good=1 if item.rating == fs.GOOD else 0,
            bad=1 if item.rating == fs.BAD else 0)
    except Exception as e:  # noqa: BLE001 - linkage is not the feedback
        logger.debug("Could not link feedback to an assurance record: %s", e)
        return False


def _sha() -> str:
    """The build this feedback was left against.

    Without it the item is an opinion. With it somebody can check out the
    same code and reproduce what the user saw, which is the difference
    between feedback and a bug report.
    """
    try:
        from backend.build_info import build_info

        # `.sha`, not `.git_sha`. The getattr default meant this returned
        # "" forever rather than raising, so every feedback item recorded no
        # build — which is the field that makes it reproducible.
        return str(build_info().sha or "")
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


# ==========================================================================
# §39-§45. A thumb on every answer, and what a thumbs-down becomes.
#
# The routes below are separate from the structured prompt above rather than
# folded into it, because they answer a different question. The prompt asks
# "was this accurate and useful?" once, at a chosen moment. These are always
# there, on every answer type, and most of the time nobody uses them — which
# is the point: the ones people do use are the ones that mattered enough.
#
# Leaving feedback is open to anyone signed in, including a Viewer. A user
# who is shown an answer and then refused the ability to say it was wrong
# has been asked for their trust and denied the means to withdraw it.
# Reading the queue and moving something along are not open.
# ==========================================================================


class ThumbsRequest(BaseModel):
    answer_id: str = Field(..., max_length=64)
    direction: str = Field(..., max_length=8)
    answer_kind: str = Field(default="analysis", max_length=32)
    language: str = Field(default="en", max_length=8)
    reasons: list[str] = Field(default_factory=list)
    correction: dict[str, Any] = Field(default_factory=dict)
    anchor_kind: str = Field(default="", max_length=24)
    anchor_ref: str = Field(default="", max_length=240)
    investigation_id: str = Field(default="", max_length=64)
    plan_fingerprint: str = Field(default="", max_length=64)


def _feedback_session():
    from backend.db.engine import SessionLocal

    return SessionLocal()


def _who(principal: Principal) -> str:
    return f"user:{principal.user_id}" if principal.user_id else "anonymous"


@router.get("/prompt")
def answer_prompt(answer_kind: str = "analysis", language: str = "en",
                  already_given: bool = False,
                  principal: Principal = RequireCommenter) -> dict[str, Any]:
    """§39-§41. What to render under one answer, whatever kind it is.

    Every kind gets the control, including the awkward ones. An UNSUPPORTED
    answer with no thumbs collects no capability requests, and the absence
    reads as nobody wanting the capability.
    """
    from backend.learning import better_approach as ba

    try:
        return ba.prompt(answer_kind=answer_kind, language=language,
                         already_given=already_given)
    except ba.FeedbackError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "unknown_answer_kind",
                    "message": str(exc)}) from exc


@router.post("/thumbs", status_code=status.HTTP_201_CREATED)
def thumbs(body: ThumbsRequest,
           principal: Principal = RequireCommenter) -> dict[str, Any]:
    """Record one thumb. Changes no validation score, ever.

    A thumbs-down may change at most two presentation preferences at once.
    Everything else in the correction becomes a Learning Ledger entry at
    CAPTURED, with no path to production except §42's.
    """
    from backend.learning import better_approach as ba
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        try:
            row = af.leave(
                session, answer_id=body.answer_id,
                direction=body.direction, answer_kind=body.answer_kind,
                reasons=tuple(body.reasons), correction=body.correction,
                anchor_kind=body.anchor_kind, anchor_ref=body.anchor_ref,
                user_id=_who(principal), language=body.language,
                investigation_id=body.investigation_id,
                plan_fingerprint=body.plan_fingerprint,
                build_sha=_sha(), teaching_release_id=_teaching_release())
        except (ba.FeedbackError, af.AnswerFeedbackError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "feedback_refused",
                        "message": str(exc)}) from exc
        session.commit()
        return {
            "feedback_id": row.feedback_id,
            "status": "RECEIVED",
            "changed_immediately": row.immediate_changes or {},
            "under_review": row.governed_fields or [],
            "validation_score_changed": False,
            "what_happens_next": (
                "Presentation preferences take effect now. Everything else "
                "goes through review, regression and release before it "
                "changes an answer — you can follow it under this feedback."
                if row.governed_fields else
                "Recorded. Nothing about how answers are computed has "
                "changed."
            ),
        }


@router.get("/thumbs/{feedback_id}")
def journey(feedback_id: str,
            principal: Principal = RequireCommenter) -> dict[str, Any]:
    """§45. What happened to one person's feedback, in their words."""
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        try:
            return af.journey(session, feedback_id)
        except af.AnswerFeedbackError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail={"error": "not_found",
                                        "message": str(exc)}) from exc


@router.get("/answers/{answer_id}/thumbs")
def for_answer(answer_id: str,
               principal: Principal = RequireCommenter) -> dict[str, Any]:
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        return {"answer_id": answer_id,
                "feedback": af.for_answer(session, answer_id)}


class AdvanceRequest(BaseModel):
    to: str = Field(..., max_length=32)
    reason: str = Field(default="", max_length=4000)
    linked_kind: str = Field(default="", max_length=32)
    linked_id: str = Field(default="", max_length=64)
    release_id: str = Field(default="", max_length=64)
    score_impact: dict[str, Any] = Field(default_factory=dict)


@router.post("/thumbs/{feedback_id}/advance")
def advance(feedback_id: str, body: AdvanceRequest,
            principal: Principal = RequireAdmin) -> dict[str, Any]:
    """Move feedback along §45's states. Refuses a skipped step.

    RECEIVED cannot jump to RELEASED: §42's path exists precisely so that
    nothing reaches production without review and regression, and a route
    that allowed the jump would make the path a description.
    """
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        try:
            row = af.advance(session, feedback_id, body.to,
                             by=_who(principal), reason=body.reason,
                             linked_kind=body.linked_kind,
                             linked_id=body.linked_id,
                             release_id=body.release_id,
                             score_impact=body.score_impact)
        except af.AnswerFeedbackError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "transition_refused",
                        "message": str(exc)}) from exc
        session.commit()
        return {"feedback_id": feedback_id, "status": row.status,
                "by": row.by, "reason": row.reason}


@router.get("/queue")
def queue(principal: Principal = RequireAdmin) -> dict[str, Any]:
    """§45's queue, with unopened counted separately from under review."""
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        return af.queue(session)


@router.get("/satisfaction")
def satisfaction(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """Thumbs by answer kind. Not an accuracy measure, and it says so."""
    from backend.services import answer_feedback as af

    with _feedback_session() as session:
        return af.satisfaction(session)
