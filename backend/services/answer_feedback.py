"""Per-answer feedback, over the database. §39-§45.

Three boundaries this file exists to hold.

**A thumb changes no score.** There is no code here that writes to a
validation score, an assurance status or a teaching case. §44's
`score_impact` is attached to a status transition that follows an
evaluation, and an evaluation is somebody else's job.

**A correction changes at most two presentation preferences.** §42's narrow
channel, and `better_approach.immediate()` decides which — this file applies
what that returns and nothing else.

**What the user said is never edited.** A reviewer who disagrees records a
decision in `answer_feedback_status`; the correction stays as written. The
pair is the record, and an edit destroys the half that says what CreditProbe
got wrong.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.brain import ledger as ledger_mod
from backend.learning import better_approach as ba
from backend.learning import preference as pf
from backend.models.platform import (
    AnswerFeedback,
    AnswerFeedbackStatus,
    UserFeedbackPreference,
)
from backend.services import brain_center as bc

logger = logging.getLogger(__name__)


class AnswerFeedbackError(Exception):
    """Something the feedback layer refused, and why."""


def _now() -> datetime:
    return datetime.now(UTC)


def leave(session: Session, *, answer_id: str, direction: str,
          answer_kind: str = ba.ANALYSIS, reasons: tuple[str, ...] = (),
          correction: dict[str, Any] | None = None, anchor_kind: str = "",
          anchor_ref: str = "", user_id: str = "", language: str = "en",
          tenant: str = "", **provenance: Any) -> AnswerFeedback:
    """Record one thumb, apply the presentation half, review the rest.

    Three things happen and they are deliberately different sizes. The
    feedback is written. At most two presentation preferences change at
    once. Everything else becomes a Learning Ledger entry at CAPTURED with
    no path to production — which is the whole of §42 in three statements.
    """
    thumbs = ba.record(
        answer_id=answer_id, direction=direction, answer_kind=answer_kind,
        reasons=reasons, correction=correction, anchor_kind=anchor_kind,
        anchor_ref=anchor_ref, user_id=user_id, language=language,
        tenant=tenant, **provenance)

    immediate = thumbs.immediate_changes
    if immediate and user_id:
        _apply_preferences(session, user_id, immediate, tenant=tenant)

    row = AnswerFeedback(
        feedback_id=thumbs.feedback_id,
        answer_id=thumbs.answer_id,
        direction=thumbs.direction,
        answer_kind=thumbs.answer_kind,
        language=thumbs.language,
        reasons=list(thumbs.reasons),
        correction=dict(thumbs.correction),
        anchor_kind=thumbs.anchor_kind,
        anchor_ref=thumbs.anchor_ref,
        build_sha=thumbs.build_sha,
        plan_fingerprint=thumbs.plan_fingerprint,
        teaching_release_id=thumbs.teaching_release_id,
        investigation_id=str(provenance.get("investigation_id", "")),
        immediate_changes=dict(immediate),
        governed_fields=list(thumbs.governed_fields),
        user_id=user_id,
        tenant=tenant,
    )
    session.add(row)

    session.add(AnswerFeedbackStatus(
        feedback_id=thumbs.feedback_id, status=ba.RECEIVED,
        by=user_id, tenant=tenant))

    # §43: approved feedback-derived learning enters the Learning Ledger.
    # It enters at CAPTURED and NON_PORTABLE, which is where §42's governed
    # path starts — recording that something was learned, not that anything
    # changed.
    if thumbs.governed_fields:
        entry = ledger_mod.capture(
            ledger_mod.BETTER_APPROACH,
            _ledger_summary(thumbs),
            object_kind="answer", object_id=thumbs.answer_id,
            user_id=user_id, tenant=tenant,
            body={"correction": dict(thumbs.correction),
                  "answer_kind": thumbs.answer_kind,
                  "anchor": {"kind": thumbs.anchor_kind,
                             "ref": thumbs.anchor_ref}},
            build_sha=thumbs.build_sha,
            teaching_release_id=thumbs.teaching_release_id,
            candidate_components=tuple(thumbs.governed_fields),
            related_ids={"feedback_id": thumbs.feedback_id})
        written = bc.record_learning(session, entry, tenant=tenant)
        row.ledger_entry_id = written.entry_id

    session.flush()
    logger.info("feedback %s on %s: %d immediate change(s), %d field(s) "
                "under review", thumbs.feedback_id, answer_id,
                len(immediate), len(thumbs.governed_fields))
    return row


def _ledger_summary(thumbs: ba.Thumbs) -> str:
    fields = ", ".join(thumbs.governed_fields)
    return (f"A user proposed a better approach to a {thumbs.answer_kind} "
            f"answer, covering: {fields}.")


def _apply_preferences(session: Session, user_id: str,
                       changes: dict[str, str], *, tenant: str) -> None:
    """§42's immediate half. Only what `immediate()` returned.

    Validated through `preference.apply`, which holds the closed set. A
    preference with no enumerated values would let a correction field be set
    to a paragraph of instructions, which is a prompt injection with a
    settings screen.
    """
    row = session.execute(
        select(UserFeedbackPreference).where(
            UserFeedbackPreference.user_id == user_id,
            UserFeedbackPreference.tenant == tenant)).scalar_one_or_none()
    if row is None:
        row = UserFeedbackPreference(user_id=user_id, tenant=tenant,
                                     values={}, muted_threads=[])
        session.add(row)
        session.flush()

    current = pf.Preference(user_id=user_id, tenant=tenant,
                            values=dict(row.values or {}),
                            muted_threads=list(row.muted_threads or []))
    for name, value in changes.items():
        try:
            current = pf.apply(current, name, value)
        except pf.PreferenceError as exc:
            # A refusal here is the closed set doing its job. Logged rather
            # than raised: the feedback itself is still worth recording, and
            # losing it because one preference was unrecognised would be the
            # wrong trade.
            logger.info("feedback preference %s=%s refused: %s",
                        name, value, exc)
    row.values = dict(current.values)


# ------------------------------------------------------------ §45 status


def advance(session: Session, feedback_id: str, to: str, *, by: str,
            reason: str = "", linked_kind: str = "", linked_id: str = "",
            release_id: str = "",
            score_impact: dict[str, Any] | None = None
            ) -> AnswerFeedbackStatus:
    """Move one piece of feedback along §45's states, or refuse."""
    history = statuses(session, feedback_id)
    if not history:
        raise AnswerFeedbackError(f"no feedback {feedback_id}")
    try:
        settled = ba.advance_status(history[-1].status, to, reason=reason)
    except ba.FeedbackError as exc:
        raise AnswerFeedbackError(str(exc)) from exc
    if not by.strip():
        raise AnswerFeedbackError(
            "moving feedback along needs a named person; the user is "
            "entitled to know who looked at it")

    row = AnswerFeedbackStatus(
        feedback_id=feedback_id, status=settled, reason=reason.strip(),
        by=by, linked_kind=linked_kind, linked_id=linked_id,
        release_id=release_id, score_impact=score_impact or {},
        tenant=history[-1].tenant)
    session.add(row)
    session.flush()
    return row


def statuses(session: Session,
             feedback_id: str) -> list[AnswerFeedbackStatus]:
    return list(session.execute(
        select(AnswerFeedbackStatus).where(
            AnswerFeedbackStatus.feedback_id == feedback_id).order_by(
            AnswerFeedbackStatus.created_at,
            AnswerFeedbackStatus.id)).scalars().all())


def journey(session: Session, feedback_id: str) -> dict[str, Any]:
    """§45. What happened to one person's feedback, in their words.

    Written for the user who left it rather than for a reviewer. "Received"
    with no next step tells somebody their feedback disappeared; the same
    state with the path beside it tells them what has to happen and roughly
    where it is.
    """
    row = session.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.feedback_id == feedback_id)).scalar_one_or_none()
    if row is None:
        raise AnswerFeedbackError(f"no feedback {feedback_id}")
    history = statuses(session, feedback_id)
    current = history[-1].status if history else ba.RECEIVED

    return {
        "feedback_id": row.feedback_id,
        "answer_id": row.answer_id,
        "direction": row.direction,
        "answer_kind": row.answer_kind,
        "status": current,
        "status_means": ba.STATUS_MEANS.get(current, ""),
        "next_steps": list(ba.TRANSITIONS.get(current, ())),
        "history": [{
            "status": s.status,
            "means": ba.STATUS_MEANS.get(s.status, ""),
            "reason": s.reason,
            "by": s.by,
            "linked": {"kind": s.linked_kind, "id": s.linked_id},
            "release": s.release_id,
            "score_impact": s.score_impact or {},
            "at": s.created_at.isoformat() if s.created_at else "",
        } for s in history],
        "changed_immediately": row.immediate_changes or {},
        "under_review": row.governed_fields or [],
        "governed_path": list(ba.GOVERNED_PATH),
        "raw_feedback_changed_no_score": True,
    }


def for_answer(session: Session, answer_id: str) -> list[dict[str, Any]]:
    """Every piece of feedback on one answer, with where each one got to."""
    rows = session.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.answer_id == answer_id)).scalars().all()
    return [journey(session, r.feedback_id) for r in rows]


# ---------------------------------------------------- §45 the review queue


def queue(session: Session, *, tenant: str = "",
          limit: int = 100) -> dict[str, Any]:
    """What is waiting, grouped by how long it has been waiting there.

    Reports RECEIVED separately from UNDER_REVIEW on purpose. A queue that
    added them would show a healthy number while nobody had opened anything,
    and "received" is the state that costs a bank its users' willingness to
    give feedback at all.
    """
    rows = session.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.tenant == tenant).order_by(
            AnswerFeedback.created_at.desc()).limit(limit)).scalars().all()

    tally = dict.fromkeys(ba.STATUSES, 0)
    items: list[dict[str, Any]] = []
    for row in rows:
        history = statuses(session, row.feedback_id)
        current = history[-1].status if history else ba.RECEIVED
        tally[current] = tally.get(current, 0) + 1
        items.append({
            "feedback_id": row.feedback_id,
            "answer_id": row.answer_id,
            "direction": row.direction,
            "answer_kind": row.answer_kind,
            "language": row.language,
            "status": current,
            "under_review": row.governed_fields or [],
            "anchor": {"kind": row.anchor_kind, "ref": row.anchor_ref},
            "created_at": row.created_at.isoformat()
            if row.created_at else "",
        })

    return {
        "by_status": tally,
        "unopened": tally.get(ba.RECEIVED, 0),
        "items": items,
        "note": (
            "Received is counted separately from under review. A queue that "
            "added them would look healthy while nobody had opened "
            "anything, and 'nobody looked' is the state that costs a bank "
            "its users' willingness to give feedback at all."
        ),
    }


def satisfaction(session: Session, *, tenant: str = "") -> dict[str, Any]:
    """Thumbs by answer kind. Not an accuracy measure, and it says so.

    Split by kind because the shapes differ and the average hides it: a
    clarification disliked by everyone and an analysis liked by everyone
    average to something that describes neither.
    """
    rows = session.execute(
        select(AnswerFeedback).where(
            AnswerFeedback.tenant == tenant)).scalars().all()
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_kind.setdefault(row.answer_kind, {"up": 0, "down": 0})
        bucket["up" if row.direction == ba.UP else "down"] += 1
    return {
        "by_answer_kind": by_kind,
        "total": len(rows),
        "not_an_accuracy_measure": (
            "This counts what people liked. An answer can be liked and "
            "wrong, and a wrong answer nobody rated is invisible here. "
            "Accuracy is measured against the sealed holdout, and no thumb "
            "moves it."
        ),
    }
