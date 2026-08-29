"""
Feedback and governed learning, over HTTP. §7-§39.

Who may do what
----------------
Giving feedback is open to every signed-in role, because §7 says every answer
and the people most likely to notice a wrong one are the analysts who read
them all day. A control only administrators could use would collect feedback
from the people least exposed to the product.

Reading the Inbox is an analyst's; reviewing candidates, building and
activating releases and training models are an administrator's. Those are the
acts that change what CreditProbe does.

What no route here does
------------------------
Nothing writes an Assurance status, a score, a plan, a result, a
certification, a teaching release, a prompt, a routing policy, a model
selection, an ontology version or a method version. `backend/learning/guard.py`
audits this module's source for exactly that, and `/guard` returns the audit
so a reviewer can see the rule holding rather than take it on trust.
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
from backend.db.engine import get_session
from backend.learning import candidate as cd
from backend.learning import feedback as fb
from backend.learning import guard as gd
from backend.learning import models as ml
from backend.learning import observation as ob
from backend.learning import release as lr
from backend.learning import replay as rp
from backend.services import learning as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["learning"])


def _tenant(principal: Principal) -> str:
    return str(getattr(principal, "tenant", "") or "")


def _user(principal: Principal) -> str:
    return str(getattr(principal, "user_id", "") or "")


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------


@router.get("/prompt")
def prompt(principal: Principal = RequireCommenter,
           answer_id: str = "", thread_id: str = "",
           complete: bool = True, is_error: bool = False,
           is_skeleton: bool = False,
           already_answered: bool = False) -> dict[str, Any]:
    """Whether to show the feedback prompt on one answer, and its wording.

    The decision is made here rather than in the client so that the rules in
    §7 have one implementation. A client that decided for itself would drift,
    and the first thing to drift would be the suppressions — which are the
    half of §7 that protects the user rather than the product.
    """
    with get_session() as session:
        found = svc.preference_for(session, _user(principal),
                                   tenant=_tenant(principal))
    placement = fb.placement(
        complete=complete, is_error=is_error, is_skeleton=is_skeleton,
        already_answered=already_answered,
        thread_muted=found.thread_muted(thread_id) if thread_id else False,
        user_muted=found.prompts_muted)
    return {**placement.to_dict(), "answer_id": answer_id,
            "categories": [{"id": c, "label": label, "means": means}
                           for c, label, means in fb.CATEGORIES],
            "consent_question": fb.CONSENT_QUESTION,
            "consent_options": {c: fb.CONSENT_MEANS[c]
                                for c in fb.CONSENTS},
            "detail_on": sorted(fb.WANTS_DETAIL),
            "dont_ask_again_in_this_thread": bool(thread_id)}


class CorrectionBody(BaseModel):
    conclusion: str = ""
    value: str = ""
    preferred_dataset: str = ""
    preferred_period: str = ""
    preferred_method: str = ""
    expected_visualization: str = ""
    reference: str = ""


class SatisfactionBody(BaseModel):
    reason: str = ""
    satisfaction: int | None = None
    helpfulness: int | None = None
    clarity: int | None = None
    trust: int | None = None
    used_as: list[str] = Field(default_factory=list)


class FeedbackBody(BaseModel):
    """One reply to "Was this answer accurate and useful?"."""

    rating: str = Field(..., description="; ".join(fb.ANSWERS))
    answer_id: str = Field(..., min_length=1)
    categories: list[str] = Field(default_factory=list)
    comment: str = ""
    correction: CorrectionBody | None = None
    satisfaction: SatisfactionBody | None = None
    consent: str = fb.CONSENT_UNSET
    surface: str = fb.COCKPIT
    # The links. Supplied by the client from the answer it is about, because
    # only the client knows which answer the user was looking at.
    project_id: str = ""
    investigation_id: str = ""
    message_id: str = ""
    question: str = ""
    answer_text: str = ""
    agentic_run_id: str = ""
    plan_fingerprint: str = ""
    assurance_record_id: str = ""
    build_sha: str = ""
    officer_level: int | None = None
    officer_title: str = ""
    agents: list[str] = Field(default_factory=list)


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def leave_feedback(body: FeedbackBody,
                   principal: Principal = RequireCommenter) -> dict[str, Any]:
    fields = body.model_dump(exclude={"rating", "answer_id", "correction",
                                      "satisfaction"})
    try:
        with get_session() as session:
            found = svc.record_feedback(
                session, rating=body.rating, answer_id=body.answer_id,
                correction=fb.Correction(**(body.correction.model_dump()
                                            if body.correction else {})),
                satisfaction=fb.Satisfaction(
                    **(body.satisfaction.model_dump()
                       if body.satisfaction else {})),
                tenant=_tenant(principal), user_id=_user(principal),
                **fields)
            session.commit()
            return found
    except fb.FeedbackError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/feedback/{event_id}/revise")
def revise(event_id: str, body: FeedbackBody,
           principal: Principal = RequireCommenter) -> dict[str, Any]:
    """A change of mind is a new event. Nothing is overwritten. §10."""
    del principal
    try:
        with get_session() as session:
            found = svc.revise_feedback(
                session, event_id, rating=body.rating,
                categories=body.categories, comment=body.comment,
                consent=body.consent)
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e


# ---------------------------------------------------------------------------
# Preferences. §13 channel A.
# ---------------------------------------------------------------------------


@router.get("/preferences")
def preferences(principal: Principal = RequireCommenter) -> dict[str, Any]:
    with get_session() as session:
        return svc.preference_for(session, _user(principal),
                                  tenant=_tenant(principal)).to_dict()


class PreferenceBody(BaseModel):
    name: str
    value: str


@router.post("/preferences")
def set_preference(body: PreferenceBody,
                   principal: Principal = RequireCommenter) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.set_preference(session, _user(principal), body.name,
                                       body.value, tenant=_tenant(principal))
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class MuteBody(BaseModel):
    thread_id: str = Field(..., min_length=1)


@router.post("/preferences/mute-thread")
def mute_thread(body: MuteBody,
                principal: Principal = RequireCommenter) -> dict[str, Any]:
    """"Don't ask again in this thread." §7."""
    with get_session() as session:
        found = svc.mute_thread(session, _user(principal), body.thread_id,
                                tenant=_tenant(principal))
        session.commit()
        return found


# ---------------------------------------------------------------------------
# The Feedback & Learning area. §16.
# ---------------------------------------------------------------------------


@router.get("/inbox")
def inbox(principal: Principal = RequireAnalyst, rating: str = "",
          limit: int = 50) -> dict[str, Any]:
    with get_session() as session:
        rows = svc.inbox(session, tenant=_tenant(principal), rating=rating,
                         limit=limit)
    return {"events": rows, "count": len(rows),
            "ratings": {a: fb.ANSWER_MEANS[a] for a in fb.ANSWERS}}


@router.get("/observations")
def observations(principal: Principal = RequireAnalyst, label: str = "",
                 limit: int = 100) -> dict[str, Any]:
    with get_session() as session:
        rows = svc.observations(session, tenant=_tenant(principal),
                                label=label, limit=limit)
    return {"observations": rows, "count": len(rows),
            "labels": dict(ob.LABEL_MEANS),
            "note": ("An observation with no feedback is UNLABELED, not "
                     "satisfied. Silence is the commonest response to a "
                     "feedback prompt.")}


@router.get("/candidates")
def candidates(principal: Principal = RequireAnalyst,
               case_status: str = "", limit: int = 100) -> dict[str, Any]:
    with get_session() as session:
        rows = svc.candidates(session, tenant=_tenant(principal),
                              status=case_status, limit=limit)
    return {"candidates": rows, "count": len(rows),
            "statuses": dict(cd.STATUS_MEANS),
            "failure_classes": dict(cd.CLASSES)}


@router.post("/candidates/from-feedback/{event_id}",
             status_code=status.HTTP_201_CREATED)
def propose(event_id: str,
            principal: Principal = RequireAdmin) -> dict[str, Any]:
    del principal
    try:
        with get_session() as session:
            found = svc.propose_candidate(session, event_id)
            session.commit()
            return found
    except (svc.LearningServiceError, cd.CandidateError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class ProposalBody(BaseModel):
    """What review says SHOULD have happened.

    Deliberately separate from the user's correction, which is stored on the
    candidate and never copied into these fields by any code path.
    """

    reading: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    officer: int | None = None
    agents: list[str] = Field(default_factory=list)
    outcome: str = ""
    datasets: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ReviewBody(BaseModel):
    action: str = Field(..., description="; ".join(svc.ACTIONS))
    reason: str = Field(..., min_length=1)
    proposal: ProposalBody | None = None


@router.post("/candidates/{candidate_id}/review")
def review(candidate_id: str, body: ReviewBody,
           principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.review_candidate(
                session, candidate_id, action=body.action,
                reviewer=_user(principal), reason=body.reason,
                proposal=(body.proposal.model_dump() if body.proposal
                          else None))
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/candidates/{candidate_id}/history")
def history(candidate_id: str,
            principal: Principal = RequireAnalyst) -> dict[str, Any]:
    del principal
    with get_session() as session:
        return {"decisions": svc.review_history(session, candidate_id)}


@router.get("/actions")
def actions(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§17's ten reviewer actions, and what each does."""
    del principal
    return {"actions": [{"action": name, "to_status": to,
                         "means": means}
                        for name, (to, means) in svc.ACTIONS.items()],
            "note": "Every action needs a reason, including a rejection."}


# ---------------------------------------------------------------------------
# Releases. §24.
# ---------------------------------------------------------------------------


class BuildBody(BaseModel):
    teaching_release_id: str = ""
    regulatory_release_id: str = ""
    note: str = ""


@router.post("/releases", status_code=status.HTTP_201_CREATED)
def build_release(body: BuildBody,
                  principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.build_release(
                session, created_by=_user(principal),
                tenant=_tenant(principal),
                teaching_release_id=body.teaching_release_id,
                regulatory_release_id=body.regulatory_release_id,
                note=body.note)
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class EvaluateBody(BaseModel):
    critical_before: int = 0
    critical_after: int = 0
    improved: dict[str, bool] = Field(default_factory=dict)
    safety_regressions: list[str] = Field(default_factory=list)
    holdout_overlap: list[str] = Field(default_factory=list)


@router.post("/releases/{release_id}/evaluate")
def evaluate(release_id: str, body: EvaluateBody,
             principal: Principal = RequireAdmin) -> dict[str, Any]:
    del principal
    try:
        with get_session() as session:
            found = svc.evaluate_release(
                session, release_id, critical_before=body.critical_before,
                critical_after=body.critical_after, improved=body.improved,
                safety_regressions=body.safety_regressions,
                holdout_overlap=body.holdout_overlap)
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("/releases/{release_id}/activate")
def activate(release_id: str,
             principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.activate_release(session, release_id,
                                         approver=_user(principal))
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


class RollbackBody(BaseModel):
    why: str = Field(..., min_length=1)


@router.post("/releases/rollback")
def rollback(body: RollbackBody,
             principal: Principal = RequireAdmin) -> dict[str, Any]:
    try:
        with get_session() as session:
            found = svc.rollback_release(session, approver=_user(principal),
                                         why=body.why,
                                         tenant=_tenant(principal))
            session.commit()
            return found
    except svc.LearningServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/releases")
def releases(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    with get_session() as session:
        rows = svc.releases(session, tenant=_tenant(principal))
        active = svc.active_release(session, tenant=_tenant(principal))
    return {"releases": rows,
            "active": active.release_id if active else "",
            "gates": dict(lr.GATES),
            "note": ("Production uses one active release. Rollback is "
                     "activating the previous one — nothing was deleted to "
                     "get here.")}


# ---------------------------------------------------------------------------
# Replay Lab. §37.
# ---------------------------------------------------------------------------


class ReplayCase(BaseModel):
    case_id: str
    question: str = ""
    production: dict[str, Any] = Field(default_factory=dict)
    candidate: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    critical: bool = False


class ReplayBody(BaseModel):
    release_id: str = ""
    cases: list[ReplayCase] = Field(default_factory=list)


@router.post("/replays", status_code=status.HTTP_201_CREATED)
def record_replay(body: ReplayBody,
                  principal: Principal = RequireAdmin) -> dict[str, Any]:
    """Compare production with a candidate, case by case.

    Improvements and regressions are reported separately and never netted: a
    release that fixes six cases and breaks one that matters is a worse
    release, and one "net +5" number is how it ships.
    """
    run = rp.Run(run_id=f"rep-{uuid.uuid4().hex[:14]}",
                 release_id=body.release_id, tenant=_tenant(principal),
                 cases=[rp.compare(c.case_id, c.production, c.candidate,
                                   question=c.question, expected=c.expected,
                                   critical=c.critical)
                        for c in body.cases])
    with get_session() as session:
        found = svc.record_replay(session, run)
        session.commit()
    return found


@router.get("/replays")
def replays(principal: Principal = RequireAnalyst,
            release_id: str = "") -> dict[str, Any]:
    with get_session() as session:
        rows = svc.replays(session, tenant=_tenant(principal),
                           release_id=release_id)
    return {"replays": rows, "axes": [{"axis": a, "material": material,
                                       "means": means}
                                      for a, material, means in rp.AXES]}


# ---------------------------------------------------------------------------
# Local models. §20, §21.
# ---------------------------------------------------------------------------


@router.get("/models")
def models(principal: Principal = RequireAnalyst,
           task: str = "") -> dict[str, Any]:
    with get_session() as session:
        rows = svc.training_runs(session, tenant=_tenant(principal),
                                 task=task)
    return {"runs": rows,
            "tasks": [{"task": name, "decides": decides,
                       "baseline": baseline}
                      for name, (decides, baseline) in ml.TASKS.items()],
            "forbidden": dict(ml.FORBIDDEN_TASKS),
            "note": ("Every task here is a classifier or a ranker over "
                     "structured features. None writes prose and none "
                     "replaces a governed calculation. A local model that "
                     "does not beat the deterministic baseline is not "
                     "activated.")}


# ---------------------------------------------------------------------------
# Metrics and the guard
# ---------------------------------------------------------------------------


@router.get("/metrics/satisfaction")
def satisfaction(principal: Principal = RequireAnalyst,
                 days: int = 30) -> dict[str, Any]:
    with get_session() as session:
        return svc.satisfaction_metrics(session, tenant=_tenant(principal),
                                        days=days)


@router.get("/metrics/learning")
def learning(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    with get_session() as session:
        return svc.learning_metrics(session, tenant=_tenant(principal))


@router.get("/guard")
def guard(principal: Principal = RequireAnalyst) -> dict[str, Any]:
    """§11, audited, so the rule can be seen holding rather than trusted.

    Open to any analyst on purpose. "Feedback cannot change the scores" is a
    claim the product makes to its users, and a claim only administrators can
    verify is a claim.
    """
    del principal
    return gd.report().to_dict()


__all__ = ["router"]
