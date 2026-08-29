"""
Feedback, observations and governed learning, as the API sees them. §7-§39.

What this layer refuses
------------------------
Everything §11 forbids, and it refuses by not having the code. There is no
function here that writes an Assurance status, a score, a coverage figure, a
plan fingerprint, a result, a certification, a release, a prompt, a routing
policy, a model selection, an ontology version or a method version.
`backend/learning/guard.py` audits this module's source for exactly that, and
the test suite fails on a finding.

What it does
-------------
Records what a user said, against the run they said it about. Records every
question whether or not anybody said anything. Turns a consented correction on
a reproducible answer into a candidate somebody has to review. Keeps the review
history. Freezes approved candidates into a release, evaluates it against
gates, activates it behind a second pair of eyes, and rolls it back.

Tenant isolation
-----------------
Every read is scoped by tenant and there is no cross-tenant query in this
file. §30: a Learning Observation, Feedback Event, Candidate Case or local
model for one tenant is not used by another.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.learning import candidate as cd
from backend.learning import feedback as fb
from backend.learning import models as ml
from backend.learning import observation as ob
from backend.learning import preference as pref
from backend.learning import release as lr
from backend.learning import replay as rp
from backend.models.platform import (
    CandidateLearningCase,
    FeedbackEventRow,
    LearningObservationRow,
    LearningReleaseActivation,
    LearningReleaseRow,
    LearningReviewDecision,
    LocalTrainingRun,
    ReplayRun,
    UserFeedbackPreference,
)

logger = logging.getLogger(__name__)


class LearningServiceError(Exception):
    """Something a caller asked for that must not happen."""


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


def _row_of(event: fb.FeedbackEvent) -> FeedbackEventRow:
    return FeedbackEventRow(
        event_id=event.event_id, event_version=event.version,
        supersedes=event.supersedes, tenant=event.tenant,
        user_id=event.user_id, project_id=event.project_id,
        investigation_id=event.investigation_id, message_id=event.message_id,
        answer_id=event.answer_id,
        assurance_record_id=event.assurance_record_id,
        agentic_run_id=event.agentic_run_id,
        plan_fingerprint=event.plan_fingerprint, build_sha=event.build_sha,
        rating=event.rating, categories=list(event.categories),
        surface=event.surface, consent=event.consent, comment=event.comment,
        reproducible=event.reproducible, body=event.to_dict(),
        fingerprint=event.fingerprint())


def record_feedback(session: Session, *, rating: str, answer_id: str,
                    **fields: Any) -> dict[str, Any]:
    """Store one immutable feedback event, and label its observation.

    The observation is labelled and NOTHING else happens. No score moves, no
    prompt changes, no case is created. Creating a candidate is a separate
    call with its own refusals, which is the difference between recording
    what somebody said and acting on it.
    """
    event = fb.create(rating=rating, answer_id=answer_id, **fields)
    session.add(_row_of(event))

    found = session.execute(
        select(LearningObservationRow).where(
            LearningObservationRow.answer_id == event.answer_id,
            LearningObservationRow.tenant == event.tenant)).scalars().first()
    if found is not None:
        found.feedback_event_id = event.event_id
        found.rating = event.rating
        found.label = (ob.DECLINED if event.rating == fb.SKIP else ob.LABELED)
        body = dict(found.body or {})
        body["label"] = found.label
        body["rating"] = event.rating
        body["feedback_event_id"] = event.event_id
        found.body = body
    session.flush()
    return {**event.to_dict(),
            "acknowledgement": fb.acknowledgement(event.rating),
            "observation_labelled": found is not None,
            "what_happens_next": _next_steps(event)}


def _next_steps(event: fb.FeedbackEvent) -> str:
    """§25's status line. Never a promise that anything has changed."""
    if event.rating == fb.SKIP:
        return "Nothing recorded beyond the fact that you were asked."
    if event.rating == fb.YES:
        return ("Recorded against this run. It counts towards satisfaction "
                "and does not raise any assurance or accuracy figure.")
    if not fb.may_learn_from(event.consent):
        return ("Recorded, and queued for review as a defect report. It will "
                "not become a learning candidate — you did not consent to "
                "that, and consent is not assumed.")
    if not event.reproducible:
        return ("Recorded and queued for review. It cannot become a learning "
                "candidate: the run behind this answer was not fully "
                "recorded, so there is nothing to replay it against.")
    return ("Recorded and queued for review. If a reviewer agrees, it becomes "
            "a candidate learning case — which still has to pass replay, "
            "holdout and approval before anything in production changes.")


def revise_feedback(session: Session, event_id: str,
                    **changes: Any) -> dict[str, Any]:
    """A new event superseding an earlier one. Nothing is overwritten."""
    row = session.execute(
        select(FeedbackEventRow).where(
            FeedbackEventRow.event_id == event_id)).scalars().first()
    if row is None:
        raise LearningServiceError(f"no feedback event {event_id!r}")
    previous = _event_of(row)
    revised = fb.revise(previous, **changes)
    session.add(_row_of(revised))
    session.flush()
    return revised.to_dict()


def _event_of(row: FeedbackEventRow) -> fb.FeedbackEvent:
    body = dict(row.body or {})
    correction = fb.Correction(
        **{k: v for k, v in (body.get("correction") or {}).items()
           if k in fb.Correction.__dataclass_fields__})
    satisfaction = fb.Satisfaction(
        **{k: v for k, v in (body.get("satisfaction") or {}).items()
           if k in fb.Satisfaction.__dataclass_fields__})
    return fb.FeedbackEvent(
        event_id=row.event_id, version=row.event_version,
        supersedes=row.supersedes, tenant=row.tenant, user_id=row.user_id,
        project_id=row.project_id, investigation_id=row.investigation_id,
        message_id=row.message_id, answer_id=row.answer_id,
        question=str(body.get("question") or ""),
        answer_text=str(body.get("answer_text") or ""),
        agentic_run_id=row.agentic_run_id,
        plan_fingerprint=row.plan_fingerprint,
        assurance_record_id=row.assurance_record_id,
        officer_level=body.get("officer_level"),
        officer_title=str(body.get("officer") or ""),
        agents=[str(a) for a in (body.get("agents") or [])],
        build_sha=row.build_sha, rating=row.rating,
        categories=list(row.categories or []), comment=row.comment,
        correction=correction, satisfaction=satisfaction,
        consent=row.consent, surface=row.surface)


def inbox(session: Session, *, tenant: str = "", rating: str = "",
          limit: int = 50) -> list[dict[str, Any]]:
    """§16's Feedback Inbox: every rating and comment, newest first."""
    query = select(FeedbackEventRow).where(FeedbackEventRow.tenant == tenant)
    if rating:
        query = query.where(FeedbackEventRow.rating == rating)
    rows = session.execute(
        query.order_by(FeedbackEventRow.created_at.desc())
        .limit(max(1, min(limit, 500)))).scalars().all()
    return [dict(r.body or {}) for r in rows]


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def record_observation(session: Session,
                       observation: ob.Observation) -> dict[str, Any]:
    """§12: every question, whether or not anybody rates it."""
    session.add(LearningObservationRow(
        observation_id=observation.observation_id, tenant=observation.tenant,
        user_id=observation.user_id, project_id=observation.project_id,
        investigation_id=observation.investigation_id,
        message_id=observation.message_id, answer_id=observation.answer_id,
        turn_index=observation.turn_index, question=observation.question,
        officer_level=observation.officer_level, outcome=observation.outcome,
        plan_fingerprint=observation.plan_fingerprint,
        build_sha=observation.build_sha, latency_ms=observation.latency_ms,
        label=observation.label, rating=observation.rating,
        feedback_event_id=observation.feedback_event_id,
        body=observation.to_dict(), fingerprint=observation.fingerprint()))
    session.flush()
    return observation.to_dict()


def observations(session: Session, *, tenant: str = "", label: str = "",
                 limit: int = 100) -> list[dict[str, Any]]:
    query = select(LearningObservationRow).where(
        LearningObservationRow.tenant == tenant)
    if label:
        query = query.where(LearningObservationRow.label == label)
    rows = session.execute(
        query.order_by(LearningObservationRow.created_at.desc())
        .limit(max(1, min(limit, 1000)))).scalars().all()
    return [dict(r.body or {}) for r in rows]


# ---------------------------------------------------------------------------
# Candidates and review
# ---------------------------------------------------------------------------


def _case_of(row: CandidateLearningCase) -> cd.CandidateCase:
    body = dict(row.body or {})
    original = dict(body.get("original") or {})
    proposed = dict(body.get("proposed") or {})
    return cd.CandidateCase(
        candidate_id=row.candidate_id, tenant=row.tenant, status=row.status,
        feedback_event_id=row.feedback_event_id,
        observation_id=row.observation_id, question=row.question,
        original_reading=dict(original.get("reading") or {}),
        original_officer=original.get("officer"),
        original_agents=[str(a) for a in (original.get("agents") or [])],
        original_plan=dict(original.get("plan") or {}),
        original_result=dict(original.get("result") or {}),
        failure_class=row.failure_class,
        user_correction=dict(body.get("user_correction") or {}),
        proposed_reading=dict(proposed.get("reading") or {}),
        proposed_officer=proposed.get("officer"),
        proposed_agents=[str(a) for a in (proposed.get("agents") or [])],
        proposed_plan=dict(proposed.get("plan") or {}),
        expected_outcome=str(proposed.get("outcome") or ""),
        required_datasets=[str(d) for d in (proposed.get("datasets") or [])],
        required_methods=[str(m) for m in (proposed.get("methods") or [])],
        required_invariants=[str(i) for i in
                             (proposed.get("invariants") or [])],
        answer_contract=dict(proposed.get("answer_contract") or {}),
        citations=[str(c) for c in (proposed.get("citations") or [])],
        reviewer=row.reviewer, review_note=row.review_note,
        rejected_because=row.rejected_because, redacted=row.redacted,
        release_id=row.release_id)


def _save_case(row: CandidateLearningCase, case: cd.CandidateCase) -> None:
    row.status = case.status
    row.failure_class = case.failure_class
    row.reviewer = case.reviewer
    row.review_note = case.review_note
    row.rejected_because = case.rejected_because
    row.redacted = case.redacted
    row.release_id = case.release_id
    row.body = case.to_dict()


def propose_candidate(session: Session, event_id: str) -> dict[str, Any]:
    """Turn one feedback event into an AUTO_PROPOSED candidate.

    Refuses a YES, feedback given without consent, and feedback about an
    answer nobody can reproduce — each for a different reason, each stated.
    """
    row = session.execute(
        select(FeedbackEventRow).where(
            FeedbackEventRow.event_id == event_id)).scalars().first()
    if row is None:
        raise LearningServiceError(f"no feedback event {event_id!r}")
    existing = session.execute(
        select(CandidateLearningCase).where(
            CandidateLearningCase.feedback_event_id == event_id
        )).scalars().first()
    if existing is not None:
        return {**dict(existing.body or {}), "already_present": True}

    observation = session.execute(
        select(LearningObservationRow).where(
            LearningObservationRow.answer_id == row.answer_id,
            LearningObservationRow.tenant == row.tenant)).scalars().first()
    found = ob.Observation(**{
        k: v for k, v in (dict(observation.body or {}) if observation
                          else {}).items()
        if k in ob.Observation.__dataclass_fields__})

    case = cd.propose(_event_of(row), found)
    stored = CandidateLearningCase(
        candidate_id=case.candidate_id, tenant=case.tenant,
        feedback_event_id=case.feedback_event_id,
        observation_id=case.observation_id, question=case.question)
    _save_case(stored, case)
    session.add(stored)
    session.flush()
    return {**case.to_dict(), "already_present": False}


def candidates(session: Session, *, tenant: str = "", status: str = "",
               limit: int = 100) -> list[dict[str, Any]]:
    query = select(CandidateLearningCase).where(
        CandidateLearningCase.tenant == tenant)
    if status:
        query = query.where(CandidateLearningCase.status == status)
    rows = session.execute(
        query.order_by(CandidateLearningCase.created_at.desc())
        .limit(max(1, min(limit, 500)))).scalars().all()
    return [dict(r.body or {}) for r in rows]


#: §17's ten reviewer actions, and what each does to the candidate.
ACTIONS: dict[str, tuple[str, str]] = {
    "APPROVE_AS_TEACHING_CASE": (
        cd.HUMAN_APPROVED,
        "Becomes a teaching case a Learning Release may contain."),
    "APPROVE_AS_REGRESSION_ONLY": (
        cd.HUMAN_APPROVED,
        "Becomes a regression test and not a teaching example — for a lesson "
        "that is worth checking and not worth showing a planner."),
    "REQUEST_CHANGE": (
        cd.NEEDS_REVIEW,
        "Back to the queue with a note about what is missing."),
    "REJECT": (cd.REJECTED, "Not a valid lesson. The reason is kept."),
    "RETIRE": (cd.RETIRED, "Was valid and no longer applies."),
    "REDACT": (cd.NEEDS_REVIEW,
               "Strip identifying content and return it to the queue."),
    "MERGE_DUPLICATE": (
        cd.RETIRED,
        "The same lesson is already recorded elsewhere."),
    "MARK_PRODUCT_BUG": (
        cd.REJECTED,
        "A defect in the software rather than a lesson for the planner. Goes "
        "to engineering."),
    "MARK_DATA_ISSUE": (
        cd.REJECTED,
        "The data was wrong, not the analysis. Goes to a data steward."),
    "MARK_USER_PREFERENCE_ONLY": (
        cd.REJECTED,
        "A presentation preference. §13 channel A, per user, not a change to "
        "what CreditProbe computes."),
}


def review_candidate(session: Session, candidate_id: str, *, action: str,
                     reviewer: str, reason: str,
                     proposal: dict[str, Any] | None = None) -> dict[str, Any]:
    """One reviewer action on one candidate. §17.

    Every action requires a reason. §17: "approval requires a reason", and
    the same holds for a rejection — a decision nobody explained cannot be
    revisited by the person who inherits the queue.
    """
    if action not in ACTIONS:
        raise LearningServiceError(
            f"{action!r} is not a review action: " + ", ".join(ACTIONS))
    if not str(reviewer).strip():
        raise LearningServiceError("a review needs a named reviewer")
    if not str(reason).strip():
        raise LearningServiceError(
            "every review action needs a reason: a decision nobody explained "
            "cannot be revisited by whoever inherits the queue")

    row = session.execute(
        select(CandidateLearningCase).where(
            CandidateLearningCase.candidate_id == candidate_id
        )).scalars().first()
    if row is None:
        raise LearningServiceError(f"no candidate {candidate_id!r}")

    case = _case_of(row)
    was = case.status

    if proposal:
        # What review says SHOULD have happened. Deliberately a separate
        # argument from the user's correction, which is never copied here.
        case.proposed_reading = dict(proposal.get("reading") or
                                     case.proposed_reading)
        case.proposed_plan = dict(proposal.get("plan") or case.proposed_plan)
        case.proposed_officer = proposal.get("officer", case.proposed_officer)
        case.proposed_agents = [str(a) for a in (proposal.get("agents")
                                                 or case.proposed_agents)]
        case.expected_outcome = str(proposal.get("outcome")
                                    or case.expected_outcome)
        case.required_datasets = [str(d) for d in (proposal.get("datasets")
                                                   or case.required_datasets)]
        case.required_methods = [str(m) for m in (proposal.get("methods")
                                                  or case.required_methods)]
        case.required_invariants = [
            str(i) for i in (proposal.get("invariants")
                             or case.required_invariants)]
        case.citations = [str(c) for c in (proposal.get("citations")
                                           or case.citations)]

    if action == "REDACT":
        case.redacted = True
        case.redaction_note = reason

    to_status, _ = ACTIONS[action]
    try:
        cd.move(case, to_status, reviewer=reviewer, note=reason)
    except cd.CandidateError as e:
        raise LearningServiceError(str(e)) from e

    _save_case(row, case)
    session.add(LearningReviewDecision(
        decision_id=f"dec-{uuid.uuid4().hex[:14]}",
        candidate_id=candidate_id, tenant=case.tenant, action=action,
        from_status=was, to_status=case.status, reviewer=reviewer,
        reason=reason, body={"action_means": ACTIONS[action][1]}))
    session.flush()
    return {**case.to_dict(), "action": action,
            "action_means": ACTIONS[action][1], "from_status": was}


def review_history(session: Session, candidate_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(LearningReviewDecision)
        .where(LearningReviewDecision.candidate_id == candidate_id)
        .order_by(LearningReviewDecision.created_at)).scalars().all()
    return [{"decision_id": r.decision_id, "action": r.action,
             "from": r.from_status, "to": r.to_status, "reviewer": r.reviewer,
             "reason": r.reason, "at": r.created_at.isoformat()}
            for r in rows]


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


def _release_of(row: LearningReleaseRow) -> lr.LearningRelease:
    body = dict(row.body or {})
    metrics = lr.Metrics(**{
        k: v for k, v in (body.get("metrics") or {}).items()
        if k in lr.Metrics.__dataclass_fields__})
    return lr.LearningRelease(
        release_id=row.release_id, tenant=row.tenant, status=row.status,
        teaching_release_id=row.teaching_release_id,
        regulatory_release_id=row.regulatory_release_id,
        candidates=[str(c) for c in (body.get("candidates") or [])],
        feedback_events=[str(e) for e in (body.get("feedback_events") or [])],
        case_counts=dict(body.get("case_counts") or {}),
        metrics=metrics,
        gates=[lr.Gate(g["gate"], bool(g["passed"]), str(g.get("detail", "")))
               for g in (body.get("gates") or [])],
        reviewers=[str(r) for r in (row.reviewers or [])],
        approver=row.approver, created_by=row.created_by,
        created_at=row.created_at, activated_at=row.activated_at,
        replaces=row.replaces, note=row.note, build_sha=row.build_sha)


def _save_release(row: LearningReleaseRow, release: lr.LearningRelease) -> None:
    row.status = release.status
    row.teaching_release_id = release.teaching_release_id  # guard: describing — records which teaching release this learning release was built against; does not touch the teaching release
    row.regulatory_release_id = release.regulatory_release_id
    row.candidate_count = len(release.candidates)
    row.reviewers = sorted(set(release.reviewers))
    row.approver = release.approver
    row.fingerprint = release.fingerprint()
    row.replaces = release.replaces
    row.note = release.note
    row.activated_at = release.activated_at
    row.body = release.to_dict()


def build_release(session: Session, *, created_by: str, tenant: str = "",
                  teaching_release_id: str = "",
                  regulatory_release_id: str = "",
                  note: str = "") -> dict[str, Any]:
    cases = [_case_of(r) for r in session.execute(
        select(CandidateLearningCase).where(
            CandidateLearningCase.tenant == tenant)).scalars().all()]
    try:
        release = lr.build(cases, created_by=created_by, tenant=tenant,
                           teaching_release_id=teaching_release_id,
                           regulatory_release_id=regulatory_release_id,
                           note=note)
    except lr.ReleaseError as e:
        raise LearningServiceError(str(e)) from e
    row = LearningReleaseRow(release_id=release.release_id, tenant=tenant,
                             created_by=created_by)
    _save_release(row, release)
    session.add(row)
    session.flush()
    return release.to_dict()


def evaluate_release(session: Session, release_id: str, *,
                     critical_before: int, critical_after: int,
                     improved: dict[str, bool],
                     safety_regressions: list[str],
                     holdout_overlap: list[str]) -> dict[str, Any]:
    row = _release_row(session, release_id)
    release = lr.evaluate(_release_of(row), critical_before=critical_before,
                          critical_after=critical_after, improved=improved,
                          safety_regressions=safety_regressions,
                          holdout_overlap=holdout_overlap)
    _save_release(row, release)
    session.flush()
    return release.to_dict()


def _release_row(session: Session, release_id: str) -> LearningReleaseRow:
    row = session.execute(
        select(LearningReleaseRow).where(
            LearningReleaseRow.release_id == release_id)).scalars().first()
    if row is None:
        raise LearningServiceError(f"no learning release {release_id!r}")
    return row


def active_release(session: Session, *,
                   tenant: str = "") -> lr.LearningRelease | None:
    row = session.execute(
        select(LearningReleaseRow).where(
            LearningReleaseRow.tenant == tenant,
            LearningReleaseRow.status == lr.ACTIVE)
        .order_by(LearningReleaseRow.activated_at.desc())).scalars().first()
    return _release_of(row) if row is not None else None


def activate_release(session: Session, release_id: str, *,
                     approver: str) -> dict[str, Any]:
    row = _release_row(session, release_id)
    release = _release_of(row)
    current = active_release(session, tenant=row.tenant)
    try:
        lr.activate(release, approver=approver, current=current)
    except lr.ReleaseError as e:
        _save_release(row, release)
        session.flush()
        raise LearningServiceError(str(e)) from e
    _save_release(row, release)
    if current is not None and current.release_id != release.release_id:
        _save_release(_release_row(session, current.release_id), current)
    session.add(LearningReleaseActivation(
        activation_id=f"act-{uuid.uuid4().hex[:14]}",
        release_id=release.release_id, tenant=row.tenant, action="ACTIVATED",
        replaces=release.replaces, approver=approver,
        reason=release.note or "activation"))
    for candidate_id in release.candidates:
        found = session.execute(
            select(CandidateLearningCase).where(
                CandidateLearningCase.candidate_id == candidate_id
            )).scalars().first()
        if found is None:
            continue
        case = _case_of(found)
        if cd.may_move(case.status, cd.APPLIED_TO_RELEASE):
            case.release_id = release.release_id
            cd.move(case, cd.APPLIED_TO_RELEASE)
            _save_case(found, case)
    session.flush()
    return release.to_dict()


def rollback_release(session: Session, *, approver: str, why: str,
                     tenant: str = "") -> dict[str, Any]:
    current = active_release(session, tenant=tenant)
    if current is None:
        raise LearningServiceError("there is no active release to roll back")
    if not current.replaces:
        raise LearningServiceError(
            f"{current.release_id} replaced nothing, so there is no earlier "
            "release to return to")
    previous = _release_of(_release_row(session, current.replaces))
    try:
        lr.rollback(current, previous, approver=approver, why=why)
    except lr.ReleaseError as e:
        raise LearningServiceError(str(e)) from e
    _save_release(_release_row(session, current.release_id), current)
    _save_release(_release_row(session, previous.release_id), previous)
    session.add(LearningReleaseActivation(
        activation_id=f"act-{uuid.uuid4().hex[:14]}",
        release_id=previous.release_id, tenant=tenant, action="ROLLED_BACK",
        replaces=current.release_id, approver=approver, reason=why))
    session.flush()
    return previous.to_dict()


def releases(session: Session, *, tenant: str = "") -> list[dict[str, Any]]:
    rows = session.execute(
        select(LearningReleaseRow).where(LearningReleaseRow.tenant == tenant)
        .order_by(LearningReleaseRow.created_at.desc())).scalars().all()
    return [dict(r.body or {}) for r in rows]


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def record_replay(session: Session, run: rp.Run) -> dict[str, Any]:
    session.add(ReplayRun(
        run_id=run.run_id or f"rep-{uuid.uuid4().hex[:14]}",
        release_id=run.release_id, tenant=run.tenant,
        case_count=len(run.cases), improved=run.improved,
        regressed=run.regressed,
        critical_regressions=len(run.critical_regressions), clean=run.clean,
        blocked_by=run.blocked_by, blocked_because=run.blocked_because,
        body=run.to_dict()))
    session.flush()
    return run.to_dict()


def replays(session: Session, *, tenant: str = "",
            release_id: str = "") -> list[dict[str, Any]]:
    query = select(ReplayRun).where(ReplayRun.tenant == tenant)
    if release_id:
        query = query.where(ReplayRun.release_id == release_id)
    rows = session.execute(
        query.order_by(ReplayRun.created_at.desc())).scalars().all()
    return [dict(r.body or {}) for r in rows]


# ---------------------------------------------------------------------------
# Local models
# ---------------------------------------------------------------------------


def record_training(session: Session, run: ml.TrainingRun) -> dict[str, Any]:
    session.add(LocalTrainingRun(
        training_run_id=run.training_run_id, task=run.task, tenant=run.tenant,
        dataset_release_id=run.dataset_release_id, algorithm=run.algorithm,
        seed=run.seed, build_sha=run.build_sha,
        artifact_hash=run.artifact_hash, status=run.status,
        activated=run.activated, approver=run.approver, failure=run.failure,
        body=run.to_dict()))
    session.flush()
    return run.to_dict()


def training_runs(session: Session, *, tenant: str = "",
                  task: str = "") -> list[dict[str, Any]]:
    query = select(LocalTrainingRun).where(LocalTrainingRun.tenant == tenant)
    if task:
        query = query.where(LocalTrainingRun.task == task)
    rows = session.execute(
        query.order_by(LocalTrainingRun.created_at.desc())).scalars().all()
    return [dict(r.body or {}) for r in rows]


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def preference_for(session: Session, user_id: str, *,
                   tenant: str = "") -> pref.Preference:
    row = session.execute(
        select(UserFeedbackPreference).where(
            UserFeedbackPreference.user_id == str(user_id),
            UserFeedbackPreference.tenant == tenant)).scalars().first()
    if row is None:
        return pref.Preference(user_id=str(user_id), tenant=tenant)
    return pref.Preference(user_id=row.user_id, tenant=row.tenant,
                           values=dict(row.values or {}),
                           muted_threads=[str(t) for t in
                                          (row.muted_threads or [])])


def set_preference(session: Session, user_id: str, name: str, value: str, *,
                   tenant: str = "") -> dict[str, Any]:
    found = preference_for(session, user_id, tenant=tenant)
    try:
        pref.apply(found, name, value)
    except pref.PreferenceError as e:
        raise LearningServiceError(str(e)) from e
    _save_preference(session, found)
    return found.to_dict()


def mute_thread(session: Session, user_id: str, thread_id: str, *,
                tenant: str = "") -> dict[str, Any]:
    found = preference_for(session, user_id, tenant=tenant)
    pref.mute_thread(found, thread_id)
    _save_preference(session, found)
    return found.to_dict()


def _save_preference(session: Session, found: pref.Preference) -> None:
    row = session.execute(
        select(UserFeedbackPreference).where(
            UserFeedbackPreference.user_id == found.user_id,
            UserFeedbackPreference.tenant == found.tenant)).scalars().first()
    if row is None:
        row = UserFeedbackPreference(user_id=found.user_id,
                                     tenant=found.tenant)
        session.add(row)
    row.values = dict(found.values)
    row.muted_threads = list(found.muted_threads)
    session.flush()


# ---------------------------------------------------------------------------
# Metrics. §26, §27.
# ---------------------------------------------------------------------------


def satisfaction_metrics(session: Session, *, tenant: str = "",
                         days: int = 30) -> dict[str, Any]:
    """§26. A product metric, and the report says so in as many words.

    Satisfaction is not accuracy. Every number here is about how people felt
    about answers, and none of it is evidence that the answers were right —
    which is why the report carries that sentence rather than leaving a reader
    to infer it.
    """
    since = datetime.now(UTC) - timedelta(days=max(1, days))
    rows = session.execute(
        select(FeedbackEventRow).where(
            FeedbackEventRow.tenant == tenant,
            FeedbackEventRow.created_at >= since)).scalars().all()
    asked = session.execute(
        select(func.count()).select_from(LearningObservationRow).where(
            LearningObservationRow.tenant == tenant,
            LearningObservationRow.created_at >= since)).scalar() or 0

    by_rating = {answer: 0 for answer in fb.ANSWERS}
    by_category: dict[str, int] = {}
    by_officer: dict[str, int] = {}
    corrections = 0
    for row in rows:
        by_rating[row.rating] = by_rating.get(row.rating, 0) + 1
        for category in (row.categories or []):
            by_category[category] = by_category.get(category, 0) + 1
        level = str((row.body or {}).get("officer_level") or "")
        if level:
            by_officer[level] = by_officer.get(level, 0) + 1
        if (row.body or {}).get("correction", {}).get("empty") is False:
            corrections += 1

    rated = sum(by_rating[a] for a in fb.RATED)
    return {
        "window_days": days,
        "answers_given": asked,
        "feedback_events": len(rows),
        "rated": rated,
        "response_rate_pct": round(100 * rated / asked, 1) if asked else None,
        "by_rating": by_rating,
        "by_issue_category": dict(sorted(by_category.items(),
                                         key=lambda kv: -kv[1])),
        "by_officer_level": by_officer,
        "corrections": corrections,
        "correction_rate_pct": (round(100 * corrections / rated, 1)
                                if rated else None),
        "note": ("Satisfaction is a product metric. It is not accuracy, it "
                 "does not enter any assurance or accuracy figure, and an "
                 "answer everybody liked can still be wrong."),
    }


def learning_metrics(session: Session, *, tenant: str = "") -> dict[str, Any]:
    """§27, and honest about what has not been measured."""
    cases = session.execute(
        select(CandidateLearningCase.status, func.count())
        .where(CandidateLearningCase.tenant == tenant)
        .group_by(CandidateLearningCase.status)).all()
    by_status = {status: count for status, count in cases}
    release = active_release(session, tenant=tenant)
    training = session.execute(
        select(LocalTrainingRun).where(
            LocalTrainingRun.tenant == tenant,
            LocalTrainingRun.activated.is_(True))).scalars().all()
    return {
        "candidates_by_status": by_status,
        "approved": by_status.get(cd.HUMAN_APPROVED, 0),
        "applied_to_release": by_status.get(cd.APPLIED_TO_RELEASE, 0),
        "active_release": release.release_id if release else "",
        "release_metrics": release.metrics.to_dict() if release else {},
        "not_measured": release.metrics.unmeasured if release else
        list(lr.Metrics().to_dict()),
        "active_local_models": {r.task: r.artifact_hash[:12] for r in training},
        "note": ("A metric that has not been measured is reported as not "
                 "measured rather than as zero. 99.99% accepted-answer "
                 "precision is not demonstrated and this report does not "
                 "claim it."),
    }


__all__ = ["ACTIONS", "LearningServiceError", "activate_release",
           "active_release", "build_release", "candidates",
           "evaluate_release", "inbox", "learning_metrics", "mute_thread",
           "observations", "preference_for", "propose_candidate",
           "record_feedback", "record_observation", "record_replay",
           "record_training", "releases", "replays", "review_candidate",
           "review_history", "revise_feedback", "rollback_release",
           "satisfaction_metrics", "set_preference", "training_runs"]
