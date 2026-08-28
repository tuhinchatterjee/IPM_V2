"""
Governed events: the things CreditProbe may act on. §34.

An event is a *fact that occurred*, recorded once. The recording is the point:
`(kind, idempotency_key)` is unique, so a dataset publication delivered twice —
by a retry, a replay, an operator pressing the button again — produces one
event, therefore one agentic run, therefore one set of Risk Cases. §70's "no
duplicate cases on replay" starts here and is finished by `risk_cases.dedupe_key`.

What an event is not
--------------------
It is not a message bus and it is not a trigger. `record()` writes the fact;
whether anything happens next is `accept()`'s decision, and that decision is
made against governed state — is the period actually published? is a schedule
enabled? — rather than against the event's own claim about itself.

That separation matters because events arrive from places that are not
authoritative. A publication hook can fire before the Parquet is readable. An
event that immediately started a review would produce a review of a period that
is not there.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.models.platform import AgentEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kinds — §34's list
# ---------------------------------------------------------------------------

DATASET_RECEIVED = "DATASET_RECEIVED"
DATASET_VALIDATED = "DATASET_VALIDATED"
DATASET_PUBLISHED = "DATASET_PUBLISHED"
NEW_PERIOD_AVAILABLE = "NEW_PERIOD_AVAILABLE"
DATA_QUALITY_ALERT = "DATA_QUALITY_ALERT"
RELATIONSHIP_FAILED = "RELATIONSHIP_FAILED"
RISK_THRESHOLD_BREACHED = "RISK_THRESHOLD_BREACHED"
WATCHLIST_CHANGED = "WATCHLIST_CHANGED"
WORKFLOW_RESPONSE = "WORKFLOW_RESPONSE"
USER_REQUESTED_REVIEW = "USER_REQUESTED_REVIEW"
SCHEDULED_PORTFOLIO_REVIEW = "SCHEDULED_PORTFOLIO_REVIEW"

KINDS: tuple[str, ...] = (
    DATASET_RECEIVED, DATASET_VALIDATED, DATASET_PUBLISHED,
    NEW_PERIOD_AVAILABLE, DATA_QUALITY_ALERT, RELATIONSHIP_FAILED,
    RISK_THRESHOLD_BREACHED, WATCHLIST_CHANGED, WORKFLOW_RESPONSE,
    USER_REQUESTED_REVIEW, SCHEDULED_PORTFOLIO_REVIEW,
)

LABELS: dict[str, str] = {
    DATASET_RECEIVED: "A dataset arrived",
    DATASET_VALIDATED: "A dataset passed validation",
    DATASET_PUBLISHED: "A dataset was published",
    NEW_PERIOD_AVAILABLE: "A new reporting period is available",
    DATA_QUALITY_ALERT: "A data quality rule failed",
    RELATIONSHIP_FAILED: "A governed relationship failed",
    RISK_THRESHOLD_BREACHED: "A risk threshold was breached",
    WATCHLIST_CHANGED: "The watchlist changed",
    WORKFLOW_RESPONSE: "Somebody responded to a workflow item",
    USER_REQUESTED_REVIEW: "A review was requested",
    SCHEDULED_PORTFOLIO_REVIEW: "A scheduled portfolio review is due",
}

#: Which events start a proactive agentic review. The rest are recorded and
#: available to look at — an event log that only holds the events that trigger
#: something cannot answer "why did nothing happen".
STARTS_REVIEW: frozenset[str] = frozenset({
    NEW_PERIOD_AVAILABLE, SCHEDULED_PORTFOLIO_REVIEW, USER_REQUESTED_REVIEW,
})

RECEIVED = "received"
ACCEPTED = "accepted"
IGNORED = "ignored"
FAILED = "failed"


def _now() -> datetime:
    return datetime.now(UTC)


def key_for(kind: str, *, period: str = "", dataset: str = "",
            object_id: str = "") -> str:
    """The natural key for one occurrence.

    A new period is one occurrence per period. A publication is one per dataset
    per period. Deliberately NOT time-based: a key with a timestamp in it makes
    every delivery unique, which is the same as having no idempotency at all.
    """
    parts = [p for p in (dataset, period, object_id) if p]
    return f"{kind.lower()}:{'|'.join(parts) or 'global'}"


def record(session: Any, *, kind: str, period: str = "", dataset: str = "",
           object_type: str = "", object_id: str = "",
           payload: dict[str, Any] | None = None,
           actor_id: int | None = None,
           idempotency_key: str = "") -> tuple[AgentEvent, bool]:
    """Record that something happened, once.

    Returns `(event, created)`. A repeat delivery returns the original event
    and `False`, and the caller can tell the difference — which matters,
    because "we already did this" and "we just did this" lead to different
    replies to whoever asked.
    """
    natural = idempotency_key or key_for(
        kind, period=period, dataset=dataset, object_id=object_id)

    existing = session.execute(
        select(AgentEvent).where(AgentEvent.kind == kind,
                                 AgentEvent.idempotency_key == natural)
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("event already recorded: %s/%s", kind, natural)
        return existing, False

    from sqlalchemy.exc import IntegrityError

    event = AgentEvent(
        kind=kind, idempotency_key=natural,
        object_type=object_type or ("dataset" if dataset else ""),
        object_id=object_id or dataset or "", period=period or "",
        payload=dict(payload or {}), status=RECEIVED, actor_id=actor_id)
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError:
        # The unique index fired: another caller recorded the same occurrence
        # between our SELECT and our INSERT. Theirs is as good as ours.
        found = session.execute(
            select(AgentEvent).where(AgentEvent.kind == kind,
                                     AgentEvent.idempotency_key == natural)
        ).scalar_one_or_none()
        if found is None:
            raise
        return found, False

    logger.info("event recorded: %s/%s", kind, natural)
    return event, True


def accept(session: Any, event: AgentEvent, *, reason: str = "") -> AgentEvent:
    event.status = ACCEPTED
    event.reason = reason or ""
    session.flush()
    return event


def ignore(session: Any, event: AgentEvent, *, reason: str) -> AgentEvent:
    """Record that nothing will happen, and why.

    An ignored event is more useful than a missing one. "The period is not
    published yet" answers the question somebody asks when the Cockpit did not
    update; an absent row does not.
    """
    event.status = IGNORED
    event.reason = reason
    session.flush()
    return event


def failed(session: Any, event: AgentEvent, *, reason: str) -> AgentEvent:
    event.status = FAILED
    event.reason = reason[:2000]
    session.flush()
    return event


def ready(session: Any, event: AgentEvent) -> tuple[bool, str]:
    """Is this event actually actionable against governed state?

    Checked against the data rather than trusting the event, because a
    publication hook can fire before the Parquet is readable and a review of a
    period that is not there produces an empty answer with a confident tone.
    """
    if event.kind not in STARTS_REVIEW:
        return False, (f"{LABELS.get(event.kind, event.kind)} is recorded but "
                       f"does not start a review.")

    period = (event.period or "").strip()
    if not period:
        return False, "The event names no reporting period."

    from backend.agentic import screening
    from backend.data_access.duckdb_source import DuckDBSource

    try:
        periods = list(DuckDBSource().periods(screening.FACILITIES))
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return False, f"The portfolio dataset could not be read: {exc}"

    if period not in periods:
        return False, (f"{period} is not published in "
                       f"{screening.FACILITIES}. The most recent published "
                       f"period is {periods[-1] if periods else 'none'}.")
    return True, f"{period} is published and ready to review."


def latest_period() -> str:
    """The most recent published portfolio period, from the data itself."""
    from backend.agentic import screening
    from backend.data_access.duckdb_source import DuckDBSource

    try:
        periods = list(DuckDBSource().periods(screening.FACILITIES))
    except Exception:  # noqa: BLE001
        return ""
    return periods[-1] if periods else ""


def listing(session: Any, *, limit: int = 50,
            kind: str = "") -> list[dict[str, Any]]:
    query = select(AgentEvent).order_by(AgentEvent.created_at.desc()).limit(limit)
    if kind:
        query = query.where(AgentEvent.kind == kind)
    return [view(e) for e in session.execute(query).scalars().all()]


def view(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "kind": event.kind,
        "label": LABELS.get(event.kind, event.kind),
        "idempotency_key": event.idempotency_key,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "period": event.period,
        "status": event.status,
        "reason": event.reason,
        "payload": dict(event.payload or {}),
        "at": event.created_at.isoformat() if event.created_at else None,
    }


__all__ = [
    "ACCEPTED",
    "DATASET_PUBLISHED",
    "DATASET_RECEIVED",
    "DATASET_VALIDATED",
    "DATA_QUALITY_ALERT",
    "FAILED",
    "IGNORED",
    "KINDS",
    "LABELS",
    "NEW_PERIOD_AVAILABLE",
    "RECEIVED",
    "RELATIONSHIP_FAILED",
    "RISK_THRESHOLD_BREACHED",
    "SCHEDULED_PORTFOLIO_REVIEW",
    "STARTS_REVIEW",
    "USER_REQUESTED_REVIEW",
    "WATCHLIST_CHANGED",
    "WORKFLOW_RESPONSE",
    "accept",
    "failed",
    "ignore",
    "key_for",
    "latest_period",
    "listing",
    "ready",
    "record",
    "view",
]
