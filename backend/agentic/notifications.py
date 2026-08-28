"""
Telling people what the agents did. §65.

Extends the existing notification centre rather than building a second one —
`platform.Notification` already carries a kind, a title, a body and an object
reference, and the Cockpit already reads it. What is added here is the agentic
vocabulary and, more importantly, the rules about *when not to notify*.

When not to notify
------------------
This is most of the design. A proactive system that notifies on everything it
notices becomes a system people mute, and a muted notification centre is worse
than none because it looks like it is working.

So:

- Only cases created NOW. A refreshed case has been notified already; telling
  somebody again every quarter that Contracting is still deteriorating is noise
  they already know about.
- Only cases above a severity floor. A LOW case belongs in Requires Attention,
  not in somebody's evening.
- One notification per run for the portfolio-level summary, not one per case.
  Eleven separate "a new borrower case" notifications from one review is the
  review shouting.
- Never to a VIEWER who owns nothing. §57: results are filtered to the viewing
  user's permissions, and that includes not being told about work they cannot
  open.

Deep links
----------
§65 asks for a deep link to the exact case, run or approval. `object_type` and
`object_id` carry it, and the Cockpit turns them into a URL — so the link is
built where the routes are known rather than being a string stored in a row that
outlives the route.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.agentic import severity as sv
from backend.api.permissions import Role
from backend.models.platform import Notification, RiskCase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kinds — §65's list
# ---------------------------------------------------------------------------

PORTFOLIO_CASE = "portfolio_case"
SEGMENT_CASE = "segment_case"
BORROWER_CASE = "borrower_case"
CASE_ASSIGNED = "case_assigned"
CASE_DUE = "case_due"
CASE_COMMENT = "case_comment"
RUN_FAILED = "agentic_run_failed"
APPROVAL_REQUIRED = "approval_required"
REVIEW_COMPLETE = "review_complete"

KINDS: tuple[str, ...] = (
    PORTFOLIO_CASE, SEGMENT_CASE, BORROWER_CASE, CASE_ASSIGNED, CASE_DUE,
    CASE_COMMENT, RUN_FAILED, APPROVAL_REQUIRED, REVIEW_COMPLETE,
)

#: Below this, a case goes into Requires Attention and nobody is interrupted.
NOTIFY_AT = sv.HIGH

#: Who is told about a completed proactive review. Everybody who can act on a
#: case; a VIEWER is told only about cases assigned to them.
AUDIENCE: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.DATA_STEWARD, Role.ANALYST})


def _above_floor(band: str) -> bool:
    return sv.ORDER.get(band, 0) >= sv.ORDER.get(NOTIFY_AT, 3)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def notify(session: Any, *, user_id: int, kind: str, title: str,
           body: str = "", object_type: str = "", object_id: str = "",
           actor_id: int | None = None) -> Notification:
    row = Notification(
        user_id=user_id, kind=kind, title=title[:300], body=body or "",
        object_type=object_type or "", object_id=str(object_id or ""),
        actor_id=actor_id)
    session.add(row)
    return row


def review_complete(session: Any, *, run_id: int, period: str,
                    created: list[int]) -> list[int]:
    """One notification per person for a finished proactive review. §35.11.

    One, not eleven. The summary names the counts and links to the run; the
    cases themselves are in Requires Attention, which is where somebody looks
    at eleven of anything.
    """
    if not created:
        return []

    rows = list(session.execute(
        select(RiskCase).where(RiskCase.id.in_(created))
    ).scalars().all())
    notable = [c for c in rows if _above_floor(c.severity)]

    audience = _audience(session)
    if not audience:
        logger.info("no audience for review %s; nothing sent", run_id)
        return []

    counted = _counts(rows)
    title = f"CreditProbe reviewed {period}"
    body = (f"{counted}. "
            + (f"{len(notable)} at {NOTIFY_AT} severity or above. "
               if notable else "")
            + "Open Requires Attention to triage them.")

    for user_id in audience:
        notify(session, user_id=user_id, kind=REVIEW_COMPLETE, title=title,
               body=body, object_type="agent_run", object_id=str(run_id))
    session.flush()
    logger.info("review %s notified %s user(s)", run_id, len(audience))
    return audience


def _counts(rows: list[RiskCase]) -> str:
    from backend.agentic import cases

    by_level: dict[str, int] = {}
    for row in rows:
        by_level[row.level] = by_level.get(row.level, 0) + 1
    parts = [f"{n} {cases.LEVEL_LABELS.get(level, level).lower()} "
             f"{'case' if n == 1 else 'cases'}"
             for level, n in by_level.items() if n]
    if not parts:
        return "No new cases"
    if len(parts) == 1:
        return parts[0].capitalize()
    return (f"{', '.join(parts[:-1])} and {parts[-1]}").capitalize()


def _audience(session: Any) -> list[int]:
    """Who is told. Everyone who can act on a case.

    Read from the user table rather than from a configured list, so a new
    analyst is included the day they are created rather than the day somebody
    remembers to add them.
    """
    from backend.db.models import User

    rows = session.execute(
        select(User.id, User.role).where(User.is_active.is_(True))
    ).all()
    found: list[int] = []
    for user_id, role in rows:
        try:
            if Role(str(role).upper()) in AUDIENCE:
                found.append(int(user_id))
        except ValueError:
            continue
    return found


def case_assigned(session: Any, *, case: RiskCase, user_id: int,
                  actor_id: int | None = None) -> Notification:
    """§65 — somebody now owns this."""
    return notify(
        session, user_id=user_id, kind=CASE_ASSIGNED,
        title=f"You own: {case.title}",
        body=(f"{case.severity.title()} severity, {case.period}. "
              f"{case.conclusion}"),
        object_type="risk_case", object_id=str(case.id), actor_id=actor_id)


def case_comment(session: Any, *, case: RiskCase, user_id: int, body: str,
                 actor_id: int | None = None) -> Notification | None:
    if user_id == actor_id:
        # Telling somebody about their own comment.
        return None
    return notify(
        session, user_id=user_id, kind=CASE_COMMENT,
        title=f"New comment on: {case.title}", body=body[:1000],
        object_type="risk_case", object_id=str(case.id), actor_id=actor_id)


def case_due(session: Any, *, case: RiskCase) -> Notification | None:
    if case.owner_id is None:
        return None
    return notify(
        session, user_id=case.owner_id, kind=CASE_DUE,
        title=f"Due soon: {case.title}",
        body=f"{case.severity.title()} severity, due "
             f"{case.due_at.date().isoformat() if case.due_at else 'soon'}.",
        object_type="risk_case", object_id=str(case.id))


def run_failed(session: Any, *, run_id: int, reason: str) -> list[int]:
    """§65 — an agentic run failed.

    Told to the people who operate the agents rather than to everybody: a
    failed background run is an operational fact, and an analyst who cannot
    open Agent Operations cannot do anything about it.
    """
    from backend.agentic import principals
    from backend.db.models import User

    rows = session.execute(
        select(User.id, User.role).where(User.is_active.is_(True))
    ).all()
    sent: list[int] = []
    for user_id, role in rows:
        try:
            if Role(str(role).upper()) not in principals.CAN_OPERATE_AGENTS:
                continue
        except ValueError:
            continue
        notify(session, user_id=int(user_id), kind=RUN_FAILED,
               title="An agentic run did not complete",
               body=reason[:1000], object_type="agent_run",
               object_id=str(run_id))
        sent.append(int(user_id))
    session.flush()
    return sent


def approval_required(session: Any, *, approval: Any) -> list[int]:
    """§65 — somebody has to decide something.

    Sent only to roles that can actually decide it. An approval request in the
    queue of somebody who cannot approve it is a request nobody will action and
    everybody will see.
    """
    from backend.agentic import approvals
    from backend.db.models import User

    rows = session.execute(
        select(User.id, User.role).where(User.is_active.is_(True))
    ).all()
    sent: list[int] = []
    for user_id, role in rows:
        if not approvals.may_decide(str(role), approval):
            continue
        notify(session, user_id=int(user_id), kind=APPROVAL_REQUIRED,
               title=f"Approval needed: {approval.title}",
               body=approval.reason[:1000], object_type="agent_approval",
               object_id=str(approval.id))
        sent.append(int(user_id))
    session.flush()
    return sent


__all__ = [
    "APPROVAL_REQUIRED",
    "AUDIENCE",
    "BORROWER_CASE",
    "CASE_ASSIGNED",
    "CASE_COMMENT",
    "CASE_DUE",
    "KINDS",
    "NOTIFY_AT",
    "PORTFOLIO_CASE",
    "REVIEW_COMPLETE",
    "RUN_FAILED",
    "SEGMENT_CASE",
    "approval_required",
    "case_assigned",
    "case_comment",
    "case_due",
    "notify",
    "review_complete",
    "run_failed",
]
