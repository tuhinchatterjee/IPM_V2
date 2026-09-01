"""
Risk Cases. §37, §38, §48–§51.

A Risk Case is NOT an Investigation
-----------------------------------
§1 says so, and the distinction is the reason the object exists. An
Investigation is a *conversation* somebody is having with the product about
something. A Risk Case is a *finding with a lifecycle*: it has an owner, a
status, a due date, a severity computed by a published formula, and it stays in
Requires Attention until a person does something about it.

A case may CAUSE an Investigation (§48), belong to a Project (§49) and enter
Workflow (§50). It is none of them.

Every figure is a reference
---------------------------
`metrics` holds numbers with the analysis run each came from. `analyses` holds
run ids. `severity` is `backend/agentic/severity.py`'s arithmetic with its
components stored beside it. Nothing on a case is a figure an agent decided on,
and nothing on a case can be traced to a sentence rather than to a run.

Not creating the same case twice
--------------------------------
`dedupe_key` is a natural key — level, entity, period, and what the case is
about — with a unique constraint behind it. A replayed review UPDATES the case
it already made: the severity is recomputed, the evidence is refreshed, and the
human state (owner, status, comments) is left alone. §70 asks for "no duplicate
cases on replay", and doing it in the database rather than with a lookup is what
makes it true when two workers replay at once.

What a person has to do
-----------------------
§38: RESOLVED requires a human unless an explicit approved policy exists. There
is no policy shipped that grants it, and `resolve()` refuses an agent actor
outright — the check is not "is this allowed" but "is this a person".
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from backend.agentic import severity as sv
from backend.models.platform import RiskCase, RiskCaseEvent, RiskCaseLink

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

BORROWER = "BORROWER"
SEGMENT = "SEGMENT"
PORTFOLIO = "PORTFOLIO"
DATA_QUALITY = "DATA_QUALITY"

LEVELS: tuple[str, ...] = (PORTFOLIO, SEGMENT, BORROWER, DATA_QUALITY)

LEVEL_LABELS: dict[str, str] = {
    PORTFOLIO: "Portfolio",
    SEGMENT: "Segment",
    BORROWER: "Borrower",
    DATA_QUALITY: "Data",
}

#: The Cockpit's filter tabs. §40.
FILTERS: tuple[str, ...] = ("ALL", "PORTFOLIO", "SEGMENTS", "BORROWERS",
                            "DATA")

FILTER_LEVEL: dict[str, str] = {
    "PORTFOLIO": PORTFOLIO,
    "SEGMENTS": SEGMENT,
    "BORROWERS": BORROWER,
    "DATA": DATA_QUALITY,
}

# ---------------------------------------------------------------------------
# Lifecycle — §38
# ---------------------------------------------------------------------------

NEW = "NEW"
TRIAGED = "TRIAGED"
UNDER_REVIEW = "UNDER_REVIEW"
UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
ACTION_PENDING = "ACTION_PENDING"
MONITORING = "MONITORING"
RESOLVED = "RESOLVED"
DISMISSED = "DISMISSED"
SNOOZED = "SNOOZED"

STATUSES: tuple[str, ...] = (NEW, TRIAGED, UNDER_REVIEW, UNDER_INVESTIGATION,
                             ACTION_PENDING, MONITORING, RESOLVED, DISMISSED,
                             SNOOZED)

#: Cases that still want somebody's attention.
OPEN: frozenset[str] = frozenset({NEW, TRIAGED, UNDER_REVIEW,
                                  UNDER_INVESTIGATION, ACTION_PENDING,
                                  MONITORING})

#: Cases nothing further will happen to without a person reopening them.
CLOSED: frozenset[str] = frozenset({RESOLVED, DISMISSED})

STATUS_LABELS: dict[str, str] = {
    NEW: "New",
    TRIAGED: "Triaged",
    UNDER_REVIEW: "Under review",
    UNDER_INVESTIGATION: "Under investigation",
    ACTION_PENDING: "Action pending",
    MONITORING: "Monitoring",
    RESOLVED: "Resolved",
    DISMISSED: "Dismissed",
    SNOOZED: "Snoozed",
}

#: Statuses only a person may set. §38: "Human action is required to move to
#: RESOLVED unless an explicit approved policy exists", and DISMISSED is the
#: same decision by another name — an agent that could dismiss a case could
#: make Requires Attention empty on its own.
HUMAN_ONLY: frozenset[str] = frozenset({RESOLVED, DISMISSED})

DEFAULT_DUE_DAYS: dict[str, int] = {
    sv.CRITICAL: 2,
    sv.HIGH: 5,
    sv.MEDIUM: 14,
    sv.LOW: 30,
}


class NotPermitted(PermissionError):
    """An actor tried to do something only a person may do."""


def _now() -> datetime:
    return datetime.now(UTC)


def _key() -> str:
    return f"rc_{uuid.uuid4().hex[:12]}"


def dedupe_key(*, level: str, entity_id: str, period: str,
               about: str = "") -> str:
    """The natural key that makes a replay an update.

    Hashed rather than concatenated because a borrower name can be 200
    characters and the column is bounded; the parts are all recoverable from
    the case's own columns, so nothing is lost by hashing.
    """
    raw = "|".join([level, (entity_id or "").strip().lower(),
                    (period or "").strip(), (about or "").strip().lower()])
    return f"{level.lower()}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


# ---------------------------------------------------------------------------
# Creating and updating
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """A case an agent proposes, before it is written."""

    level: str
    title: str
    period: str
    entity: str = ""
    entity_id: str = ""
    entity_kind: str = ""
    prior_period: str = ""
    conclusion: str = ""
    why: str = ""
    about: str = ""
    exposure: float | None = None
    exposure_unit: str = "USD mn"
    metrics: list[dict[str, Any]] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    analyses: list[int] = field(default_factory=list)
    score: sv.Score | None = None
    evidence_coverage: float = 0.0
    agent_run_id: int | None = None
    source_event_id: int | None = None
    trace_id: str = ""

    @property
    def key(self) -> str:
        return dedupe_key(level=self.level, entity_id=self.entity_id or
                          self.entity, period=self.period, about=self.about)


def upsert(session: Any, draft: Draft, *, actor_agent: str = "") -> RiskCase:
    """Create the case, or refresh the one this review already made.

    The human state — owner, status, comments, due date, links — is NEVER
    overwritten by a refresh. A review that ran again and reset a case somebody
    had triaged to NEW would undo a person's work every time it ran, which is
    the specific way a proactive system becomes something people switch off.
    """
    existing = session.execute(
        select(RiskCase).where(RiskCase.dedupe_key == draft.key)
    ).scalar_one_or_none()

    score = draft.score or sv.Score()
    if existing is not None:
        moved = abs(existing.severity_score - score.score) > 0.0001
        existing.title = draft.title or existing.title
        existing.conclusion = draft.conclusion or existing.conclusion
        existing.why = draft.why or existing.why
        existing.exposure = draft.exposure
        existing.metrics = list(draft.metrics)
        existing.signals = list(draft.signals)
        existing.evidence = dict(draft.evidence)
        existing.analyses = list(draft.analyses)
        existing.severity = score.band
        existing.severity_score = score.score
        existing.severity_detail = score.to_dict()
        existing.severity_version = score.version
        existing.evidence_coverage = draft.evidence_coverage
        existing.priority = sv.priority(
            score, exposure=draft.exposure,
            unresolved_days=_age_days(existing.created_at),
            overdue=_overdue(existing.due_at))
        existing.agent_run_id = draft.agent_run_id or existing.agent_run_id
        existing.updated_at = _now()
        _record(session, existing, kind="refreshed",
                body=(f"Refreshed against {draft.period}."
                      + (f" Severity moved to {score.band}." if moved else "")),
                actor_agent=actor_agent,
                detail={"severity": score.band, "score": score.score})
        session.flush()
        logger.info("risk case %s refreshed (%s)", existing.id, score.band)
        return existing

    case = RiskCase(
        case_key=_key(),
        title=draft.title,
        level=draft.level,
        entity=draft.entity,
        entity_id=draft.entity_id or draft.entity,
        entity_kind=draft.entity_kind,
        period=draft.period,
        prior_period=draft.prior_period,
        severity=score.band,
        severity_score=score.score,
        severity_detail=score.to_dict(),
        severity_version=score.version,
        priority=sv.priority(score, exposure=draft.exposure),
        evidence_coverage=draft.evidence_coverage,
        exposure=draft.exposure,
        exposure_unit=draft.exposure_unit,
        metrics=list(draft.metrics),
        signals=list(draft.signals),
        conclusion=draft.conclusion,
        why=draft.why,
        evidence=dict(draft.evidence),
        analyses=list(draft.analyses),
        source_event_id=draft.source_event_id,
        agent_run_id=draft.agent_run_id,
        trace_id=draft.trace_id,
        status=NEW,
        due_at=_now() + timedelta(days=DEFAULT_DUE_DAYS.get(score.band, 14)),
        dedupe_key=draft.key,
    )
    session.add(case)
    session.flush()
    _record(session, case, kind="created",
            body=draft.conclusion or draft.title,
            to_status=NEW, actor_agent=actor_agent,
            detail={"severity": score.band, "score": score.score})
    for run_id in draft.analyses:
        link(session, case, object_type="analysis", object_id=str(run_id),
             label="Governed analysis behind this case", relation="evidence")
    session.flush()
    logger.info("risk case %s created: %s (%s)", case.id, case.title,
                score.band)
    return case


def _age_days(created: datetime | None) -> int:
    if created is None:
        return 0
    return max(0, (_now() - created).days)


def _overdue(due: datetime | None) -> bool:
    return bool(due and due < _now())


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def transition(session: Any, case: RiskCase, to: str, *,
               user_id: int | None = None, actor_agent: str = "",
               note: str = "") -> RiskCase:
    """Move a case to a new status.

    Refuses RESOLVED and DISMISSED from an agent (§38). The check is on the
    ACTOR rather than on a permission, because the requirement is not "an agent
    with enough autonomy may close a case" — it is that a person must.
    """
    if to not in STATUSES:
        raise ValueError(f"'{to}' is not a Risk Case status.")
    if to in HUMAN_ONLY and user_id is None:
        raise NotPermitted(
            f"Moving a case to {STATUS_LABELS[to]} is a person's decision. "
            f"§38 requires human action, and no approved policy grants it to "
            f"an agent.")

    was = case.status
    case.status = to
    case.updated_at = _now()
    if to == RESOLVED:
        case.resolution = note or case.resolution
    if to == DISMISSED:
        case.dismiss_reason = note or case.dismiss_reason
    _record(session, case, kind="status", from_status=was, to_status=to,
            body=note, user_id=user_id, actor_agent=actor_agent)
    session.flush()
    return case


def assign(session: Any, case: RiskCase, *, owner_id: int | None = None,
           team_id: int | None = None, user_id: int | None = None,
           note: str = "") -> RiskCase:
    case.owner_id = owner_id
    case.team_id = team_id
    if case.status == NEW:
        case.status = TRIAGED
    case.updated_at = _now()
    _record(session, case, kind="assigned", body=note, user_id=user_id,
            to_status=case.status,
            detail={"owner_id": owner_id, "team_id": team_id})
    session.flush()
    return case


def snooze(session: Any, case: RiskCase, *, days: int,
           user_id: int | None = None, note: str = "") -> RiskCase:
    """Put a case aside until a date, without closing it.

    A snooze is not a dismissal and never becomes one: the case comes back at
    `snooze_until` with its evidence intact. That is what makes snoozing a safe
    thing for an officer to do with a case they cannot act on this week.
    """
    was = case.status
    case.snooze_until = _now() + timedelta(days=max(1, days))
    case.status = SNOOZED
    case.updated_at = _now()
    _record(session, case, kind="snoozed", from_status=was, to_status=SNOOZED,
            body=note or f"Snoozed for {days} days.", user_id=user_id,
            detail={"until": case.snooze_until.isoformat()})
    session.flush()
    return case


def wake(session: Any, *, limit: int = 200) -> list[RiskCase]:
    """Return snoozed cases whose date has passed.

    Called by the schedule tick. A snooze that never ended would be a
    dismissal with extra steps.
    """
    rows = list(session.execute(
        select(RiskCase).where(RiskCase.status == SNOOZED,
                               RiskCase.snooze_until.isnot(None),
                               RiskCase.snooze_until <= _now()).limit(limit)
    ).scalars().all())
    for case in rows:
        case.status = TRIAGED
        case.snooze_until = None
        case.updated_at = _now()
        _record(session, case, kind="status", from_status=SNOOZED,
                to_status=TRIAGED, body="The snooze period ended.",
                actor_agent="workflow_coordinator")
    if rows:
        session.flush()
    return rows


def dismiss(session: Any, case: RiskCase, *, reason: str,
            user_id: int) -> RiskCase:
    """§43: dismiss with a reason. The reason is required, not optional —
    a case dismissed with no reason is one nobody can review later."""
    if not (reason or "").strip():
        raise ValueError("A dismissal needs a reason.")
    return transition(session, case, DISMISSED, user_id=user_id, note=reason)


def resolve(session: Any, case: RiskCase, *, resolution: str,
            user_id: int) -> RiskCase:
    if not (resolution or "").strip():
        raise ValueError("Resolving a case needs a note saying what happened.")
    return transition(session, case, RESOLVED, user_id=user_id,
                      note=resolution)


def comment(session: Any, case: RiskCase, *, body: str,
            user_id: int | None = None, actor_agent: str = "") -> RiskCaseEvent:
    return _record(session, case, kind="comment", body=body, user_id=user_id,
                   actor_agent=actor_agent)


def _record(session: Any, case: RiskCase, *, kind: str, body: str = "",
            from_status: str = "", to_status: str = "",
            user_id: int | None = None, actor_agent: str = "",
            detail: dict[str, Any] | None = None) -> RiskCaseEvent:
    event = RiskCaseEvent(
        case_id=case.id, kind=kind, from_status=from_status or "",
        to_status=to_status or "", body=body or "",
        detail=dict(detail or {}), actor_id=user_id,
        actor_agent=actor_agent or "")
    session.add(event)
    return event


# ---------------------------------------------------------------------------
# Links — §49: point at objects, never copy them
# ---------------------------------------------------------------------------


def link(session: Any, case: RiskCase, *, object_type: str, object_id: str,
         label: str = "", relation: str = "evidence",
         user_id: int | None = None) -> RiskCaseLink | None:
    existing = session.execute(
        select(RiskCaseLink).where(RiskCaseLink.case_id == case.id,
                                   RiskCaseLink.object_type == object_type,
                                   RiskCaseLink.object_id == str(object_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = RiskCaseLink(case_id=case.id, object_type=object_type,
                       object_id=str(object_id), label=label,
                       relation=relation, created_by=user_id)
    session.add(row)
    return row


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def listing(session: Any, *, level: str = "", statuses: Any = None,
            period: str = "", owner_id: int | None = None,
            limit: int = 50) -> list[RiskCase]:
    """Open cases, most urgent first.

    Ordered by the stored `priority` integer rather than by anything computed
    at read time, so two readers looking at the same list see the same order
    and §46's "do not let UI ordering depend solely on model prose" holds by
    construction.
    """
    query = select(RiskCase)
    query = query.where(RiskCase.status.in_(list(statuses or OPEN)))
    if level:
        query = query.where(RiskCase.level == level)
    if period:
        query = query.where(RiskCase.period == period)
    if owner_id is not None:
        query = query.where(RiskCase.owner_id == owner_id)
    query = query.order_by(RiskCase.priority.desc(),
                           RiskCase.severity_score.desc(),
                           RiskCase.created_at.desc()).limit(limit)
    return list(session.execute(query).scalars().all())


def counts(session: Any, *, period: str = "") -> dict[str, int]:
    """How many open cases at each level. §40's count badges.

    One grouped query rather than five, because five counts fetched separately
    can disagree with each other and with the list beside them.
    """
    query = (select(RiskCase.level, func.count(RiskCase.id))
             .where(RiskCase.status.in_(list(OPEN)))
             .group_by(RiskCase.level))
    if period:
        query = query.where(RiskCase.period == period)
    rows = dict(session.execute(query).all())
    found = {level: int(rows.get(level, 0)) for level in LEVELS}
    found["ALL"] = sum(found.values())
    return found


def summary_sentence(session: Any, *, period: str = "") -> str:
    """§45's one grounded sentence.

    Built from the counts, so it cannot state a number that is not backed by
    current Risk Cases — which is exactly what §45 forbids. When there is
    nothing, it says so rather than being omitted: an empty Requires Attention
    with no sentence looks broken.
    """
    found = counts(session, period=period)
    parts: list[str] = []
    for level, word, plural in (
        (PORTFOLIO, "portfolio issue", "portfolio issues"),
        (SEGMENT, "segment issue", "segment issues"),
        (BORROWER, "borrower case", "borrower cases"),
        (DATA_QUALITY, "data issue", "data issues"),
    ):
        n = found.get(level, 0)
        if n:
            parts.append(f"{n} {word if n == 1 else plural}")

    where = f"CreditProbe reviewed {period} and " if period else "CreditProbe "
    if not parts:
        return (f"{where}found nothing that requires attention."
                if period else
                "Nothing in the book currently requires attention.")
    if len(parts) == 1:
        listed = parts[0]
    else:
        listed = f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f"{where}identified {listed} requiring review."


def view(case: RiskCase, *, events: list[RiskCaseEvent] | None = None,
         links: list[RiskCaseLink] | None = None) -> dict[str, Any]:
    """One case, as the Cockpit row and the drawer read it. §41–§43, §47."""
    return {
        "id": case.id,
        "case_key": case.case_key,
        "title": case.title,
        "level": case.level,
        "level_label": LEVEL_LABELS.get(case.level, case.level),
        "entity": case.entity,
        "entity_id": case.entity_id,
        "entity_kind": case.entity_kind,
        "period": case.period,
        "prior_period": case.prior_period,
        "severity": case.severity,
        "severity_score": case.severity_score,
        "severity_detail": dict(case.severity_detail or {}),
        "severity_version": case.severity_version,
        "priority": case.priority,
        "evidence_coverage": case.evidence_coverage,
        "exposure": case.exposure,
        "exposure_unit": case.exposure_unit,
        "metrics": list(case.metrics or []),
        "signals": list(case.signals or []),
        "conclusion": case.conclusion,
        "why": case.why,
        "evidence": dict(case.evidence or {}),
        "analyses": list(case.analyses or []),
        "status": case.status,
        "status_label": STATUS_LABELS.get(case.status, case.status),
        "open": case.status in OPEN,
        "owner_id": case.owner_id,
        "team_id": case.team_id,
        "due_at": _iso(case.due_at),
        "overdue": _overdue(case.due_at) and case.status in OPEN,
        "snooze_until": _iso(case.snooze_until),
        "dismiss_reason": case.dismiss_reason,
        "resolution": case.resolution,
        "investigation_id": case.investigation_id,
        "project_id": case.project_id,
        "workflow_item_id": case.workflow_item_id,
        "agent_run_id": case.agent_run_id,
        "trace_id": case.trace_id,
        "created_at": _iso(case.created_at),
        "updated_at": _iso(case.updated_at),
        "timeline": [_event_view(e) for e in (events or [])],
        "links": [_link_view(link_row) for link_row in (links or [])],
        "next_actions": next_actions(case),
    }


def next_actions(case: RiskCase) -> list[dict[str, str]]:
    """§47's NEXT ACTIONS, and §43's action list.

    Derived from the case's own state rather than being a fixed row of
    buttons: offering "Investigate" on a case that already has an
    Investigation, or "Resolve" on a dismissed one, is offering something that
    will not work.
    """
    found: list[dict[str, str]] = []
    if case.status in CLOSED:
        return [{"id": "reopen", "label": "Reopen",
                 "note": "Return this case to review."}]

    if case.investigation_id:
        found.append({"id": "open_investigation", "label": "Open investigation",
                      "note": "Continue the conversation already open on this."})
    else:
        found.append({"id": "investigate", "label": "Investigate",
                      "note": "Open an Investigation seeded from this case."})
    if not case.project_id:
        found.append({"id": "add_to_project", "label": "Add to project",
                      "note": "Link this case into a Project workspace."})
    if not case.owner_id:
        found.append({"id": "assign", "label": "Assign",
                      "note": "Give this case an owner."})
    found.append({"id": "review", "label": "Send for review",
                  "note": "Ask somebody to look at this."})
    found.append({"id": "snooze", "label": "Snooze",
                  "note": "Put it aside; it comes back on its own."})
    found.append({"id": "dismiss", "label": "Dismiss",
                  "note": "Close it with a reason."})
    return found


def events_of(session: Any, case_id: int,
              limit: int = 100) -> list[RiskCaseEvent]:
    return list(session.execute(
        select(RiskCaseEvent).where(RiskCaseEvent.case_id == case_id)
        .order_by(RiskCaseEvent.created_at).limit(limit)
    ).scalars().all())


def links_of(session: Any, case_id: int) -> list[RiskCaseLink]:
    return list(session.execute(
        select(RiskCaseLink).where(RiskCaseLink.case_id == case_id)
    ).scalars().all())


def load(session: Any, case_id: int) -> RiskCase | None:
    return session.get(RiskCase, case_id)


def _event_view(event: RiskCaseEvent) -> dict[str, Any]:
    from backend.agentic import registry

    agent = registry.agent(event.actor_agent) if event.actor_agent else None
    return {
        "id": event.id,
        "kind": event.kind,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "body": event.body,
        "detail": dict(event.detail or {}),
        "actor_id": event.actor_id,
        "actor_agent": event.actor_agent,
        "actor_label": (agent.business_name if agent
                        else ("CreditProbe" if event.actor_agent else "")),
        "at": _iso(event.created_at),
    }


def _link_view(row: RiskCaseLink) -> dict[str, Any]:
    return {"id": row.id, "object_type": row.object_type,
            "object_id": row.object_id, "label": row.label,
            "relation": row.relation, "at": _iso(row.created_at)}


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


__all__ = [
    "ACTION_PENDING",
    "BORROWER",
    "CLOSED",
    "DATA_QUALITY",
    "DEFAULT_DUE_DAYS",
    "DISMISSED",
    "FILTERS",
    "FILTER_LEVEL",
    "HUMAN_ONLY",
    "LEVELS",
    "LEVEL_LABELS",
    "MONITORING",
    "NEW",
    "OPEN",
    "PORTFOLIO",
    "RESOLVED",
    "SEGMENT",
    "SNOOZED",
    "STATUSES",
    "STATUS_LABELS",
    "TRIAGED",
    "UNDER_INVESTIGATION",
    "UNDER_REVIEW",
    "Draft",
    "NotPermitted",
    "assign",
    "comment",
    "counts",
    "dedupe_key",
    "dismiss",
    "events_of",
    "link",
    "links_of",
    "listing",
    "load",
    "next_actions",
    "resolve",
    "snooze",
    "summary_sentence",
    "transition",
    "upsert",
    "view",
    "wake",
]
