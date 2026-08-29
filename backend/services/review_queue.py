"""
Turning a reviewed failure into a case the factory can measure against. P0.15.

The distinction that makes this useful
--------------------------------------
A bug report says what went wrong. This says what CreditProbe should have DONE
instead, written in the same shape the curriculum specifies a case: capability,
concepts, datasets, invariants, forbidden behaviours. That is the difference
between a queue somebody reads and a queue the evaluator runs.

Two rules, and both are about the human in the middle
------------------------------------------------------
**Nothing enters the curriculum without adjudication.** An item is captured
automatically — from the cockpit, from an agentic run, from an evaluation — and
promoted only by a person who wrote down the corrected reading and why. A queue
that promotes its own contents is a product learning from its own mistakes,
which is how a wrong answer becomes the standard.

**No automatic production self-training.** P0.15 says it and this module
enforces it: nothing here reaches a model, and no weight anywhere changes
because of a row in this table. An approved item becomes a CASE — a
specification, in a corpus a person can read, that the product is evaluated
against. The learning happens when somebody fixes the product and the case goes
from FAILING to PASSING.

Regression status is not a hope
-------------------------------
An approved item starts at NOT_TESTED, which is not the same as passing. It
becomes FAILING or PASSING only by being RUN. An approved correction nobody has
executed is a description of an intention.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.platform import ReviewQueueItem

logger = logging.getLogger(__name__)

# Where an item is in its review.
CAPTURED = "CAPTURED"
UNDER_REVIEW = "UNDER_REVIEW"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
DUPLICATE = "DUPLICATE"

STATUSES: tuple[str, ...] = (CAPTURED, UNDER_REVIEW, APPROVED, REJECTED,
                             DUPLICATE)

#: Which moves are legal. A state machine rather than a free `status` column,
#: because "approved" arrived at by any path is a claim about review that no
#: review happened.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    CAPTURED: (UNDER_REVIEW, REJECTED, DUPLICATE),
    UNDER_REVIEW: (APPROVED, REJECTED, DUPLICATE),
    APPROVED: (),          # terminal: an approved case lives in the curriculum
    REJECTED: (UNDER_REVIEW,),   # a reviewer may reopen their own refusal
    DUPLICATE: (UNDER_REVIEW,),
}

# Whether the product now does what the corrected expectations say.
NOT_TESTED = "NOT_TESTED"
FAILING = "FAILING"
PASSING = "PASSING"
RETIRED = "RETIRED"

REGRESSION_STATUSES: tuple[str, ...] = (NOT_TESTED, FAILING, PASSING, RETIRED)

#: Where an item can come from.
SOURCES: tuple[str, ...] = ("cockpit", "agentic", "evaluation", "manual")


class NotPermitted(RuntimeError):
    """A transition the review model does not allow."""


def capture(session: Session, *, question: str,
            current_reading: dict[str, Any] | None = None,
            observed_plan: dict[str, Any] | None = None,
            observed_result: dict[str, Any] | None = None,
            failure_layer: str = "", failure_category: str = "",
            observed_problem: str = "", source: str = "manual",
            run_id: str = "", user_id: int | None = None,
            user_correction: str = "",
            retrieved_case_ids: list[str] | None = None,
            observed_invariants: dict[str, Any] | None = None,
            observed_interpretation: str = "",
            observed_release_id: str = "") -> ReviewQueueItem:
    """Record a failure somebody noticed.

    Deliberately cheap to call and deliberately incomplete: capture takes what
    the product already knows, and the corrected reading is what a REVIEWER
    adds. A capture step that demanded the correction up front would be a form,
    and nobody fills in a form at the moment they find a bug.

    §33's fields are all optional for the same reason. `user_correction` is
    kept apart from `observed_problem` because a user saying "these aren't the
    right customers" and a reviewer writing "the population was not narrowed to
    the carried cohort" are different evidence, and merging them loses the half
    that is not an interpretation. `retrieved_case_ids` is there because "the
    planner was shown three examples of the wrong family" is a fix and "the
    plan was wrong" is not.
    """
    item = ReviewQueueItem(
        question=str(question or "").strip(),
        current_reading=dict(current_reading or {}),
        observed_plan=dict(observed_plan or {}),
        observed_result=dict(observed_result or {}),
        failure_layer=str(failure_layer or "")[:48],
        failure_category=str(failure_category or "")[:32],
        observed_problem=str(observed_problem or ""),
        user_correction=str(user_correction or ""),
        retrieved_case_ids=list(retrieved_case_ids or []),
        observed_invariants=dict(observed_invariants or {}),
        observed_interpretation=str(observed_interpretation or ""),
        observed_release_id=str(observed_release_id or "")[:64],
        status=CAPTURED,
        regression_status=NOT_TESTED,
        source=source if source in SOURCES else "manual",
        run_id=str(run_id or "")[:64],
        created_by=user_id,
    )
    session.add(item)
    session.flush()
    return item


def from_answer(session: Session, answered: Any, *, problem: str,
                layer: str = "", source: str = "cockpit",
                user_id: int | None = None) -> ReviewQueueItem:
    """Capture straight from an answer the product produced.

    Reads the same objects the answer surface reads, so what lands in the queue
    is what the user was looking at rather than a reconstruction of it.
    """
    reading = getattr(answered, "reading", None)
    build = getattr(answered, "build", None)
    runtime = getattr(answered, "runtime", None)
    gate = getattr(answered, "gate", None)

    return capture(
        session,
        question=str(getattr(answered, "question", "") or ""),
        current_reading=(reading.to_dict()
                         if hasattr(reading, "to_dict") else {}),
        observed_plan={
            "summary": str(getattr(build, "summary", "") or ""),
            "shape": str(getattr(build, "shape", "") or ""),
            "datasets": list(getattr(build, "datasets", ()) or ()),
            "filters": [list(f) for f in (getattr(build, "filters", ()) or ())],
            "period": str(getattr(build, "period", "") or ""),
        },
        observed_result={
            "row_count": int(getattr(runtime, "row_count", 0) or 0),
            "warnings": list(getattr(runtime, "warnings", ()) or ()),
            "presentability": (gate.verdict if gate is not None else ""),
            "why": (gate.why if gate is not None else ""),
        },
        failure_layer=layer,
        failure_category=str(getattr(answered, "failure_kind", "") or ""),
        observed_problem=problem, source=source,
        run_id=str(getattr(runtime, "run_id", "") or ""),
        user_id=user_id)


def start_review(session: Session, item_id: int, *,
                 user_id: int | None = None) -> ReviewQueueItem:
    """Take an item off the pile."""
    return _move(session, item_id, UNDER_REVIEW, user_id=user_id, note="")


def approve(session: Session, item_id: int, *, corrected_reading: dict[str, Any],
            corrected_expectations: dict[str, Any], note: str,
            user_id: int | None = None) -> ReviewQueueItem:
    """A person says what the right answer would have been, and signs it.

    Every argument is required, and each one refuses something:

    - a corrected READING, or the item says a thing was wrong without saying
      what right would have looked like;
    - corrected EXPECTATIONS, or there is nothing for the evaluator to check —
      and they are a specification, never a stored figure, because a stored
      answer is one somebody quietly aligns to whatever the product returns;
    - a NOTE, because an approval with no reasoning is a click, and the
      curriculum inherits it for as long as the case survives.
    """
    if not corrected_reading:
        raise NotPermitted(
            "An approval needs the corrected reading. Recording that an answer "
            "was wrong without recording what right would have been leaves "
            "nothing anybody can act on.")
    if not corrected_expectations:
        raise NotPermitted(
            "An approval needs corrected expectations — what a right answer "
            "must DO. Without them the case cannot be evaluated, and an "
            "unevaluatable case in the curriculum is a comment.")
    if not str(note or "").strip():
        raise NotPermitted(
            "An approval needs a reason. The curriculum inherits it for as "
            "long as the case survives, and 'approved' on its own tells the "
            "next reader nothing.")

    item = _move(session, item_id, APPROVED, user_id=user_id, note=note)
    item.corrected_reading = dict(corrected_reading)
    item.corrected_expectations = dict(corrected_expectations)
    item.curriculum_case_id = f"rq-{item.id:06d}"
    # An approved item has NOT been shown to pass. It becomes FAILING or
    # PASSING by being run; until then it is untested, and saying so is the
    # difference between a queue and a wish list.
    item.regression_status = NOT_TESTED
    session.flush()
    return item


def record_release(session: Session, item_id: int, *, release_id: str,
                   teaching_case_id: str = "") -> ReviewQueueItem:
    """§33's release inclusion.

    An approved correction that has not shipped has not fixed anything, and
    that is precisely the state that looks finished on a review screen: the
    reviewer signed it, the case exists, and production is still serving the
    release that got it wrong. Recording the release is what lets a queue say
    "approved, not yet live" rather than "done".
    """
    item = session.get(ReviewQueueItem, int(item_id))
    if item is None:
        raise NotPermitted(f"There is no review item {item_id}.")
    if item.status != APPROVED:
        raise NotPermitted(
            "Only an approved item can be included in a release. An item that "
            "has not been adjudicated has nothing to include.")
    item.included_in_release = str(release_id or "")[:64]
    if teaching_case_id:
        item.teaching_case_id = str(teaching_case_id)[:64]
    session.flush()
    return item


def awaiting_release(session: Session, *,
                     limit: int = 500) -> list[ReviewQueueItem]:
    """Approved corrections that have not shipped.

    The list somebody has to look at before saying the queue is clear.
    """
    found = session.execute(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.status == APPROVED,
               ReviewQueueItem.included_in_release == "")
        .order_by(ReviewQueueItem.adjudicated_at.asc())
        .limit(int(limit)))
    return list(found.scalars())


def reject(session: Session, item_id: int, *, note: str,
           user_id: int | None = None) -> ReviewQueueItem:
    """Not a defect, or not one worth a case. The reason is required: a
    rejection nobody explained is one somebody re-files next month."""
    if not str(note or "").strip():
        raise NotPermitted("A rejection needs a reason.")
    return _move(session, item_id, REJECTED, user_id=user_id, note=note)


def mark_duplicate(session: Session, item_id: int, *, note: str,
                   user_id: int | None = None) -> ReviewQueueItem:
    if not str(note or "").strip():
        raise NotPermitted("Say which item this duplicates.")
    return _move(session, item_id, DUPLICATE, user_id=user_id, note=note)


def record_regression(session: Session, item_id: int, *, status: str
                      ) -> ReviewQueueItem:
    """What happened when the corrected expectations were actually run.

    Only an approved item has expectations to run, so only an approved item can
    carry a regression result. Recording one on a captured item would be a
    verdict on a specification nobody has written.
    """
    if status not in REGRESSION_STATUSES:
        raise NotPermitted(f"{status!r} is not a regression status.")
    item = _require(session, item_id)
    if item.status != APPROVED:
        raise NotPermitted(
            "Only an approved item has corrected expectations to run against. "
            f"This one is {item.status}.")
    item.regression_status = status
    item.regression_checked_at = datetime.now(UTC)
    session.flush()
    return item


def _move(session: Session, item_id: int, to: str, *, user_id: int | None,
          note: str) -> ReviewQueueItem:
    item = _require(session, item_id)
    allowed = TRANSITIONS.get(item.status, ())
    if to not in allowed:
        raise NotPermitted(
            f"An item that is {item.status} cannot become {to}. "
            f"From here it may only become: "
            f"{', '.join(allowed) if allowed else 'nothing — it is settled'}.")
    item.status = to
    if to in (APPROVED, REJECTED, DUPLICATE):
        item.adjudicated_by = user_id
        item.adjudicated_at = datetime.now(UTC)
    if note:
        item.adjudication_note = str(note)
    session.flush()
    return item


def _require(session: Session, item_id: int) -> ReviewQueueItem:
    item = session.get(ReviewQueueItem, item_id)
    if item is None:
        raise NotPermitted(f"No review queue item {item_id}.")
    return item


# ---------------------------------------------------------------------------
# Reading the queue
# ---------------------------------------------------------------------------


def pending(session: Session, *, limit: int = 100) -> list[ReviewQueueItem]:
    """What is waiting for a person, oldest first."""
    found = session.execute(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.status.in_((CAPTURED, UNDER_REVIEW)))
        .order_by(ReviewQueueItem.created_at)
        .limit(max(1, limit))).scalars().all()
    return list(found)


def approved(session: Session, *, limit: int = 500) -> list[ReviewQueueItem]:
    """The items that have become curriculum cases."""
    found = session.execute(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.status == APPROVED)
        .order_by(ReviewQueueItem.adjudicated_at)
        .limit(max(1, limit))).scalars().all()
    return list(found)


def specification(item: ReviewQueueItem) -> dict[str, Any]:
    """One approved item, as the specification a case is built from.

    Returns data, not a `Case`. The Intelligence Factory turns this into one —
    the dependency runs factory to backend and never the other way, because a
    backend module that can import the curriculum can reach the sealed holdout
    in one more line, and the point of the seal is that the line is never there
    to be extended.
    """
    if item.status != APPROVED:
        raise NotPermitted(
            "Only an approved item is a case. An unadjudicated failure in the "
            "curriculum is the product learning from its own mistakes.")

    spec = dict(item.corrected_expectations or {})
    return {
        "id": item.curriculum_case_id or f"rq-{item.id:06d}",
        "title": (item.observed_problem or item.question)[:120],
        "question": item.question,
        "capability": str(spec.get("capability") or ""),
        "action": str(spec.get("action") or ""),
        "datasets": list(spec.get("datasets") or ()),
        "concepts": list(spec.get("concepts") or ()),
        "period": str(spec.get("period") or ""),
        "outcome": str(spec.get("outcome") or "EXECUTE"),
        "invariants": list(spec.get("invariants") or ()),
        "forbidden": list(spec.get("forbidden") or ()),
    }


def specifications(session: Session) -> list[dict[str, Any]]:
    """Every approved item, as case specifications."""
    return [specification(item) for item in approved(session)]


def summary(session: Session) -> dict[str, Any]:
    """What the queue holds, for Agent Operations.

    Reports the untested approvals separately: an approved correction nobody
    has run is a description of an intention, and counting it beside the
    passing ones would make the queue look like progress.
    """
    items = session.execute(select(ReviewQueueItem)).scalars().all()
    by_status = {name: 0 for name in STATUSES}
    by_regression = {name: 0 for name in REGRESSION_STATUSES}
    by_layer: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        if item.status == APPROVED:
            by_regression[item.regression_status] = (
                by_regression.get(item.regression_status, 0) + 1)
        if item.failure_layer:
            by_layer[item.failure_layer] = by_layer.get(item.failure_layer, 0) + 1

    return {
        "total": len(items),
        "by_status": by_status,
        "by_regression": by_regression,
        "by_layer": dict(sorted(by_layer.items(), key=lambda kv: -kv[1])),
        "awaiting_review": by_status[CAPTURED] + by_status[UNDER_REVIEW],
        "in_curriculum": by_status[APPROVED],
        "approved_but_never_run": by_regression[NOT_TESTED],
        "self_training": False,
        "rule": ("Approved items become curriculum CASES. Nothing here trains "
                 "a model, and no weight changes because of a row in this "
                 "table."),
    }


__all__ = [
    "awaiting_release",
    "record_release",
    "APPROVED",
    "CAPTURED",
    "DUPLICATE",
    "FAILING",
    "NOT_TESTED",
    "PASSING",
    "REGRESSION_STATUSES",
    "REJECTED",
    "RETIRED",
    "SOURCES",
    "STATUSES",
    "TRANSITIONS",
    "UNDER_REVIEW",
    "NotPermitted",
    "approve",
    "approved",
    "capture",
    "from_answer",
    "mark_duplicate",
    "pending",
    "record_regression",
    "specification",
    "specifications",
    "reject",
    "start_review",
    "summary",
]
