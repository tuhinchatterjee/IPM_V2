"""
What the worker actually runs. §17, §18.

Three job kinds, three handlers, and a deliberate separation: the worker knows
about leases and heartbeats and knows nothing about credit; this module knows
about credit and nothing about leases. The only thing they share is the `Job`
and a `should_stop()` callable.

Each handler owns its own transaction. A review that creates eleven cases and
then fails on the twelfth must not roll those eleven back — they are real
findings that cost real scans, and the failure is recorded beside them rather
than instead of them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.agentic import queue

logger = logging.getLogger(__name__)


def run_agentic_job(job: queue.Job, should_stop: Callable[[], bool]) -> None:
    """A user's question, answered by a coordinated run.

    Interactive runs normally happen inline in the request — a user waiting for
    an answer does not want it queued. This path exists for a question
    deliberately handed to the background: a broad investigation that would
    time out a request, or one resumed after a worker restart.
    """
    from backend.agentic import interactive
    from backend.db.engine import get_session

    payload = job.payload or {}
    question = str(payload.get("question") or "")
    if not question:
        raise ValueError("An agentic job needs a question.")

    with get_session() as session:
        interactive.run(
            session, question=question,
            user_id=payload.get("user_id"),
            role=str(payload.get("role") or ""),
            project_id=payload.get("project_id"),
            investigation_id=payload.get("investigation_id"),
            run_id=job.run_id,
            should_stop=should_stop)


def run_proactive_job(job: queue.Job, should_stop: Callable[[], bool]) -> None:
    """A proactive review of a published period. §35."""
    from backend.agentic import review, runs
    from backend.db.engine import get_session

    payload = job.payload or {}
    period = str(payload.get("period") or "")
    prior = str(payload.get("prior_period") or "")
    trigger = str(payload.get("trigger") or runs.EVENT)

    with get_session() as session:
        run_row, found = review.run(
            session, period=period, prior_period=prior, trigger=trigger,
            event_id=payload.get("event_id"),
            user_id=payload.get("user_id"),
            should_stop=should_stop)
        if found.stopped == "failed":
            # Recorded on the run AND raised, so the queue retries it. A review
            # that failed on a transient source read is exactly the case the
            # backoff exists for.
            raise RuntimeError(found.note or "The review did not complete.")
        logger.info("review of %s produced %s case(s) (run %s)",
                    found.period, found.case_count, run_row.id)


def run_schedule_tick(job: queue.Job, should_stop: Callable[[], bool]) -> None:
    """The periodic sweep. §31.

    Three things, none of them expensive:

    - wake snoozed cases whose date has passed, so a snooze is a delay rather
      than a quiet dismissal;
    - notify owners of cases coming due;
    - enqueue any schedule whose trigger has fired.

    Deliberately does no analysis of its own. A tick that ran a review inline
    would hold the queue for minutes and starve everything behind it; it
    enqueues instead, and the review is claimed like any other job.
    """
    from backend.agentic import cases, notifications, schedules
    from backend.db.engine import get_session

    _ = job
    with get_session() as session:
        woken = cases.wake(session)
        if woken:
            logger.info("%s snoozed case(s) returned to review", len(woken))

        for case in _due_soon(session):
            notifications.case_due(session, case=case)

    if should_stop():
        return

    # Demo Mode suppresses the third of the three. Waking a snoozed case and
    # notifying an owner are cheap and truthful; a schedule firing on its own
    # halfway through a demonstration is a portfolio review competing for the
    # same database as the question being asked on screen.
    #
    # Suppressed, not disabled: a presenter clicking Run Portfolio Review
    # still runs one. What cannot happen is a run nobody started.
    from backend.demo import mode

    # Demo Mode suppresses portfolio analysis, not the Project Planner. A
    # review competes for the same database as the question on screen; the
    # planner sweep reads ten small tables and is the thing the demonstration
    # is showing — a reminder that only arrives because somebody pressed a
    # button is not a reminder.
    scopes = (None if mode.schedules_may_fire()
              else (schedules.PLANNER_SCOPE,))
    if scopes is not None:
        logger.info("Synthetic Data Mode is on: only the Project Planner "
                    "sweep fires on its own. A review started from the "
                    "screen still runs.")

    with get_session() as session:
        started = schedules.tick(session, scopes=scopes)
        if started:
            logger.info("schedule tick enqueued %s job(s)", len(started))


def _due_soon(session: Any, *, days: int = 2) -> list[Any]:
    """Owned, open cases falling due inside the window.

    Owned only: telling nobody in particular that an unassigned case is due
    would notify everybody about work nobody has accepted.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from backend.agentic import cases
    from backend.models.platform import RiskCase

    cutoff = datetime.now(UTC) + timedelta(days=days)
    return list(session.execute(
        select(RiskCase).where(
            RiskCase.status.in_(list(cases.OPEN)),
            RiskCase.owner_id.isnot(None),
            RiskCase.due_at.isnot(None),
            RiskCase.due_at <= cutoff)
        .limit(100)
    ).scalars().all())


__all__ = ["run_agentic_job", "run_proactive_job", "run_schedule_tick"]
