"""
Whether CreditProbe has actually looked. P0.13.

The defect this exists to fix
-----------------------------
The Cockpit said:

    "CreditProbe reviewed Q2 2026 and found nothing that requires attention."

No review had ever run. Zero proactive runs, zero Risk Cases. The sentence was
built from a count of cases, and a count of zero was rendered as a clean bill of
health — because "no cases exist" and "we looked and found nothing" produce the
same number and the code only had the number.

They are not the same claim. One is an absence of evidence; the other is
evidence of absence, and it is the more reassuring of the two. Telling a credit
officer their book is clean when nothing has examined it is the worst failure in
this product's class: it is not a wrong figure, it is a wrong *assurance*, and
the officer stops looking.

The five states
---------------
P0.13 names them, and the distinction the code was missing is the first two
against the fourth:

    NOT_RUN                 no current review has completed
    RUNNING                 a review is in progress
    COMPLETED_WITH_CASES    a validated review found things
    COMPLETED_NO_CASES      a validated review found nothing
    FAILED                  a review could not complete

Only COMPLETED_NO_CASES may say the book is clean, and it may say so only
because a completed, validated run is on record.

"Current"
---------
A review of Q1 is not a review of Q2. The state is always asked about a period,
and a review that completed against an earlier period leaves the current one
NOT_RUN — otherwise last quarter's clean bill silently covers this quarter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.platform import AgentRun

logger = logging.getLogger(__name__)

NOT_RUN = "NOT_RUN"
RUNNING = "RUNNING"
COMPLETED_WITH_CASES = "COMPLETED_WITH_CASES"
COMPLETED_NO_CASES = "COMPLETED_NO_CASES"
FAILED = "FAILED"

STATES: tuple[str, ...] = (NOT_RUN, RUNNING, COMPLETED_WITH_CASES,
                           COMPLETED_NO_CASES, FAILED)

#: The triggers that count as a portfolio review. A user's own question is not
#: one: answering "what is total ECL" does not mean the book has been reviewed.
REVIEW_TRIGGERS: tuple[str, ...] = ("scheduled_review", "event", "manual_review")

#: Run statuses that mean the review is still going.
LIVE: frozenset[str] = frozenset({"queued", "running", "needs_input"})

#: Run statuses that mean it finished and can be relied on.
DONE: frozenset[str] = frozenset({"succeeded", "complete", "completed"})


@dataclass
class Review:
    """What is known about whether this period has been reviewed."""

    state: str = NOT_RUN
    period: str = ""
    run_id: int | None = None
    finished_at: str = ""
    open_cases: int = 0
    #: Why the review could not complete, for FAILED.
    reason: str = ""
    #: Whether the caller may start one.
    can_run: bool = False
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def reviewed(self) -> bool:
        """Whether a completed review actually stands behind this state."""
        return self.state in (COMPLETED_WITH_CASES, COMPLETED_NO_CASES)

    def sentence(self) -> str:
        """The one line above the list. §45, and P0.13's whole point.

        Every branch says what is true. Only one of them is allowed to say the
        book is clean, and it is the only one with a completed review behind it.
        """
        where = f" of {self.period}" if self.period else ""
        if self.state == RUNNING:
            return f"A portfolio review{where} is running now."
        if self.state == FAILED:
            return (f"The portfolio review{where} could not complete"
                    + (f" — {self.reason}" if self.reason else ".")
                    + (" Nothing here has been checked." if self.reason else ""))
        if self.state == COMPLETED_WITH_CASES:
            return ""    # the case counts speak; see `summary_sentence`
        if self.state == COMPLETED_NO_CASES:
            return (f"A validated review{where} completed and found no "
                    f"governed threshold requiring attention.")
        return (f"No portfolio review{where} has been completed, so nothing "
                f"here has been checked yet.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "period": self.period,
            "run_id": self.run_id,
            "finished_at": self.finished_at,
            "open_cases": self.open_cases,
            "reason": self.reason,
            "can_run": self.can_run,
            "reviewed": self.reviewed,
            "sentence": self.sentence(),
        }


def state(session: Any, *, period: str = "", open_cases: int = 0,
          can_run: bool = False) -> Review:
    """The review state for a period, from the runs actually recorded.

    Reads `agent_runs` rather than counting cases. A case count answers "is
    there anything here"; only a run answers "has anything looked".
    """
    at = period or _latest_period()
    found = Review(period=at, open_cases=open_cases, can_run=can_run)

    row = _latest_run(session, at)
    if row is None:
        found.state = NOT_RUN
        return found

    found.run_id = row.id
    found.finished_at = _iso(getattr(row, "finished_at", None))
    status = str(getattr(row, "status", "") or "")

    if status in LIVE:
        found.state = RUNNING
        return found
    if status not in DONE:
        found.state = FAILED
        found.reason = str(getattr(row, "failure", "") or "")
        return found

    found.state = COMPLETED_WITH_CASES if open_cases else COMPLETED_NO_CASES
    return found


def _latest_run(session: Any, period: str) -> Any:
    """The most recent review OF THIS PERIOD.

    Scoped to the period on purpose: a completed review of Q1 says nothing
    about Q2, and letting it stand would be last quarter's clean bill of health
    covering this quarter's unexamined book.
    """
    query = (select(AgentRun)
             .where(AgentRun.trigger.in_(list(REVIEW_TRIGGERS)))
             .order_by(AgentRun.created_at.desc())
             .limit(1))
    if period:
        query = query.where(AgentRun.period == period)
    try:
        return session.execute(query).scalars().first()
    except Exception:  # noqa: BLE001 - an unreadable run table is NOT_RUN
        logger.exception("could not read the review state")
        return None


def _latest_period() -> str:
    from backend.agentic import events

    try:
        return events.latest_period()
    except Exception:  # noqa: BLE001
        return ""


def _iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def summary_sentence(session: Any, review: Review) -> str:
    """The line the Cockpit shows above Requires Attention.

    With cases, the existing grounded count sentence — it is backed by current
    Risk Cases, which is what §47 requires. Without them, the REVIEW state
    decides, because that is the only thing that knows whether the absence
    means anything.
    """
    from backend.agentic import cases as rc

    if review.state == COMPLETED_WITH_CASES:
        return rc.summary_sentence(session, period=review.period)
    return review.sentence()


__all__ = [
    "COMPLETED_NO_CASES",
    "COMPLETED_WITH_CASES",
    "FAILED",
    "NOT_RUN",
    "REVIEW_TRIGGERS",
    "RUNNING",
    "STATES",
    "Review",
    "state",
    "summary_sentence",
]
