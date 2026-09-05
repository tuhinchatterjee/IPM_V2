"""
Governed schedules and policies. §31, §32.

Schedules
---------
A schedule says *when* CreditProbe reviews something on its own, and — equally
— what it is allowed to do when it does. §31's fields are all present, and the
two that matter most are `approval_policy` and `budget`: a schedule that could
run without a ceiling or send without approval is a schedule that turns an
overnight job into an incident.

`tick()` decides which schedules are due and ENQUEUES them. It never runs one
inline: a sweep that ran a portfolio review would hold the queue for minutes
while every user's question waited behind it.

Policies
--------
Versioned by row, never updated in place. A policy change is evidence — "what
was the auto-create threshold when this case was made" is a question somebody
asks in a review — and a row that was edited cannot answer it. `set_policy()`
deactivates the current version and writes a new one.

What ships enabled
------------------
The publication-triggered review, because it is the demonstration's own flow.
Everything else ships disabled: a product that arrives running daily jobs
nobody asked for is one whose first act is to surprise its operator.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.agentic import autonomy, queue, screening
from backend.models.platform import AgentPolicy, AgentSchedule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Triggers — §31's list
# ---------------------------------------------------------------------------

ON_PUBLISH = "on_dataset_published"
MONTHLY = "monthly"
QUARTERLY = "quarterly"
DAILY = "daily"
WEEKLY = "weekly"
#: Cheap, deterministic work that has to notice a date turning over during a
#: working day. A portfolio review would never carry this trigger; a check of
#: which commitments have just fallen due is exactly what it is for.
HOURLY = "hourly"
MANUAL = "manual"

TRIGGERS: tuple[str, ...] = (ON_PUBLISH, MONTHLY, QUARTERLY, DAILY, WEEKLY,
                             HOURLY, MANUAL)

TRIGGER_LABELS: dict[str, str] = {
    ON_PUBLISH: "When a dataset is published",
    HOURLY: "Hourly",
    MONTHLY: "Monthly",
    QUARTERLY: "Quarterly",
    DAILY: "Daily",
    WEEKLY: "Weekly",
    MANUAL: "Only when somebody asks",
}

INTERVALS: dict[str, timedelta] = {
    HOURLY: timedelta(hours=1),
    DAILY: timedelta(days=1),
    WEEKLY: timedelta(days=7),
    MONTHLY: timedelta(days=30),
    QUARTERLY: timedelta(days=91),
}

#: The scope that means "the Project Planner's own commitments", not the credit
#: book. A schedule carrying it enqueues a planner sweep rather than a
#: portfolio review: different work, different queue kind, same governance —
#: one table an operator can see, enable and disable.
PLANNER_SCOPE = "planner_projects"

#: What a schedule may do with what it finds.
DRAFT_ONLY = "draft_only"
AUTO_ASSIGN = "auto_assign"

APPROVAL_POLICIES: tuple[str, ...] = (DRAFT_ONLY, AUTO_ASSIGN)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

SEEDS: tuple[dict[str, Any], ...] = (
    {
        "name": "New period portfolio review",
        "description": ("Reviews the whole book whenever a new portfolio "
                        "period is published: deterministic screening first, "
                        "specialists only on what it finds."),
        "trigger": ON_PUBLISH,
        "scope": "portfolio",
        "agents": ["portfolio_risk", "ifrs9", "ratings_financials",
                   "delinquency", "validation"],
        "data_requirement": [screening.FACILITIES],
        "approval_policy": DRAFT_ONLY,
        "enabled": True,
    },
    {
        "name": "Quarterly portfolio review",
        "description": "A full review on the reporting calendar.",
        "trigger": QUARTERLY,
        "scope": "portfolio",
        "agents": ["portfolio_risk", "ifrs9", "validation"],
        "data_requirement": [screening.FACILITIES],
        "approval_policy": DRAFT_ONLY,
        "enabled": False,
    },
    {
        "name": "Daily unresolved case review",
        "description": ("Wakes snoozed cases, notifies owners of cases coming "
                        "due, and re-scores what is still open."),
        "trigger": DAILY,
        "scope": "unresolved_cases",
        "agents": ["workflow_coordinator"],
        "approval_policy": DRAFT_ONLY,
        "enabled": False,
    },
    {
        "name": "Project Planner commitment sweep",
        "description": ("Checks every open project's tasks, milestones and "
                        "health, and tells the people responsible what has "
                        "moved. Deterministic and cheap: no model is asked "
                        "whether a task is late."),
        "trigger": HOURLY,
        "scope": PLANNER_SCOPE,
        "agents": [],
        "approval_policy": DRAFT_ONLY,
        # The one seed that ships enabled alongside the publication review.
        # The others are portfolio analysis, which is expensive and which an
        # operator should choose to start. This one reads ten planner tables,
        # sends only to project participants who have notifications on, and is
        # the entire promise of the feature: a planner that only knows what
        # somebody typed into it is a filing cabinet.
        "enabled": True,
    },
    {
        "name": "Weekly watchlist review",
        "description": "Re-screens the watchlist for deterioration.",
        "trigger": WEEKLY,
        "scope": "watchlist",
        "agents": ["early_warning", "validation"],
        "data_requirement": [screening.FACILITIES],
        "approval_policy": DRAFT_ONLY,
        "enabled": False,
    },
)


def seed(session: Any) -> int:
    """Write the schedules the product ships with, once.

    Idempotent by name: running it again on an existing deployment adds
    anything new and leaves an operator's own settings alone.
    """
    written = 0
    for spec in SEEDS:
        existing = session.execute(
            select(AgentSchedule).where(AgentSchedule.name == spec["name"])
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(AgentSchedule(
            name=spec["name"], description=spec.get("description", ""),
            trigger=spec["trigger"], scope=spec.get("scope", "portfolio"),
            scope_detail={}, agents=list(spec.get("agents", [])),
            methods=[], data_requirement=list(spec.get("data_requirement", [])),
            approval_policy=spec.get("approval_policy", DRAFT_ONLY),
            notify=[], budget={}, enabled=bool(spec.get("enabled", False))))
        written += 1
    if written:
        session.flush()
        logger.info("seeded %s agent schedule(s)", written)
    return written


# ---------------------------------------------------------------------------
# The tick
# ---------------------------------------------------------------------------


def due(session: Any, *, at: datetime | None = None) -> list[AgentSchedule]:
    """Which enabled schedules should fire now.

    `on_dataset_published` never fires here — it is triggered by an event, and
    a time-based sweep that also fired it would run the review twice for one
    publication.
    """
    when = at or _now()
    rows = list(session.execute(
        select(AgentSchedule).where(AgentSchedule.enabled.is_(True))
    ).scalars().all())

    found: list[AgentSchedule] = []
    for row in rows:
        if row.trigger in (ON_PUBLISH, MANUAL):
            continue
        interval = INTERVALS.get(row.trigger)
        if interval is None:
            continue
        if row.last_run_at is None or row.last_run_at + interval <= when:
            found.append(row)
    return found


def tick(session: Any, *, at: datetime | None = None,
         scopes: tuple[str, ...] | None = None) -> list[int]:
    """Enqueue every schedule that is due. Returns the job ids.

    `scopes`, when given, restricts the tick to schedules with those scopes.
    Demo Mode uses it to keep the cheap deterministic planner sweep running
    while portfolio reviews stay suppressed — the suppression exists because a
    review competes for the database during a demonstration, and a sweep of
    ten planner tables does not.
    """
    from backend.agentic import events

    started: list[int] = []
    when = at or _now()
    period = events.latest_period()

    for schedule in due(session, at=when):
        if scopes is not None and schedule.scope not in scopes:
            continue
        if schedule.scope == PLANNER_SCOPE:
            # Planner work reads the planner's own tables, so a published
            # credit period is irrelevant to it and requiring one would keep
            # it from ever firing on a deployment with no data lake.
            job_id, created = _fire_planner(session, when)
            schedule.last_run_at = when
            if created:
                started.append(job_id)
            continue
        if not _data_ready(schedule, period):
            logger.info("schedule '%s' skipped: required data is not "
                        "published for %s", schedule.name, period or "—")
            continue
        job_id, created = queue.enqueue(
            session, kind=queue.PROACTIVE_REVIEW,
            idempotency_key=f"schedule:{schedule.id}:{period}",
            payload={"period": period, "trigger": "scheduled_review",
                     "schedule_id": schedule.id},
            priority=queue.PRIORITY_SCHEDULED,
            timeout_seconds=int((schedule.budget or {}).get(
                "runtime_seconds", 1_200)))
        schedule.last_run_at = when
        if created:
            started.append(job_id)
    if started:
        session.flush()
    return started


def _fire_planner(session: Any, when: datetime) -> tuple[int, bool]:
    """Enqueue the Project Planner's sweep for the schedule's day."""
    from backend.planner import monitor as planner_monitor

    return planner_monitor.schedule(session, today=when.date())


def _data_ready(schedule: AgentSchedule, period: str) -> bool:
    """Whether the datasets a schedule needs are published at this period."""
    required = list(schedule.data_requirement or [])
    if not required or not period:
        return bool(period)
    from backend.data_access.duckdb_source import DuckDBSource

    dal = DuckDBSource()
    for dataset in required:
        try:
            if period not in list(dal.periods(dataset)):
                return False
        except Exception:  # noqa: BLE001 - unreadable is not ready
            return False
    return True


def fire(session: Any, schedule: AgentSchedule, *, period: str = "",
         user_id: int | None = None) -> tuple[int, bool]:
    """Run a schedule now, because somebody asked. §31's explicit manual run."""
    from backend.agentic import events

    at = period or events.latest_period()
    return queue.enqueue(
        session, kind=queue.PROACTIVE_REVIEW,
        idempotency_key=f"manual:{schedule.id}:{at}",
        payload={"period": at, "trigger": "manual_review",
                 "schedule_id": schedule.id, "user_id": user_id},
        priority=queue.PRIORITY_EVENT)


def listing(session: Any) -> list[dict[str, Any]]:
    rows = list(session.execute(
        select(AgentSchedule).order_by(AgentSchedule.name)).scalars().all())
    return [view(r) for r in rows]


def view(schedule: AgentSchedule) -> dict[str, Any]:
    from backend.agentic import registry

    return {
        "id": schedule.id,
        "name": schedule.name,
        "description": schedule.description,
        "trigger": schedule.trigger,
        "trigger_label": TRIGGER_LABELS.get(schedule.trigger,
                                            schedule.trigger),
        "scope": schedule.scope,
        "scope_detail": dict(schedule.scope_detail or {}),
        "agents": [
            {"agent_id": a,
             "name": (registry.agent(a).business_name
                      if registry.agent(a) else a)}
            for a in (schedule.agents or [])],
        "methods": list(schedule.methods or []),
        "data_requirement": list(schedule.data_requirement or []),
        "approval_policy": schedule.approval_policy,
        "notify": list(schedule.notify or []),
        "budget": dict(schedule.budget or {}),
        "enabled": schedule.enabled,
        "last_run_at": (schedule.last_run_at.isoformat()
                        if schedule.last_run_at else None),
        "last_run_id": schedule.last_run_id,
    }


def set_enabled(session: Any, schedule: AgentSchedule, *, enabled: bool,
                user_id: int | None = None) -> AgentSchedule:
    schedule.enabled = bool(enabled)
    schedule.updated_by = user_id
    session.flush()
    return schedule


# ---------------------------------------------------------------------------
# Policies — §32
# ---------------------------------------------------------------------------

AUTONOMY = "autonomy"
BUDGETS = "budgets"
SCREENING = "screening"
SEVERITY = "severity"
NOTIFICATION = "notification"
RETENTION = "retention"

POLICY_KEYS: tuple[str, ...] = (AUTONOMY, BUDGETS, SCREENING, SEVERITY,
                                NOTIFICATION, RETENTION)

POLICY_LABELS: dict[str, str] = {
    AUTONOMY: "What agents may do without asking",
    BUDGETS: "What a run may spend",
    SCREENING: "What counts as a material movement",
    SEVERITY: "How severity is weighted",
    NOTIFICATION: "Who is told, and when",
    RETENTION: "How long agentic records are kept",
}


def policy_defaults() -> dict[str, dict[str, Any]]:
    """The policies the product ships with.

    Nothing is pre-approved and no threshold is loosened. A demonstration that
    arrived with a permissive autonomy policy would demonstrate a product
    nobody would deploy.
    """
    from backend.agentic import budgets as bg
    from backend.agentic import severity as sv

    return {
        AUTONOMY: autonomy.policy_defaults(),
        BUDGETS: {"interactive": bg.INTERACTIVE.to_dict(),
                  "proactive": bg.PROACTIVE.to_dict()},
        SCREENING: dict(screening.thresholds()),
        SEVERITY: {"version": sv.VERSION, "weights": dict(sv.WEIGHTS),
                   "bands": {name: floor for floor, name in sv.BANDS},
                   "material_exposure": sv.MATERIAL_EXPOSURE},
        NOTIFICATION: {"notify_at_severity": "high",
                       "one_summary_per_review": True},
        RETENTION: {"runs_days": 730, "events_days": 730,
                    "resolved_cases_days": 1095},
    }


def seed_policies(session: Any) -> int:
    written = 0
    for key, value in policy_defaults().items():
        existing = session.execute(
            select(AgentPolicy).where(AgentPolicy.key == key,
                                      AgentPolicy.active.is_(True))
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(AgentPolicy(
            key=key, version=1, value=value,
            description=POLICY_LABELS.get(key, key), active=True,
            note="Shipped default."))
        written += 1
    if written:
        session.flush()
    return written


def policy(session: Any, key: str) -> dict[str, Any]:
    """The active version of a policy, or the shipped default."""
    row = session.execute(
        select(AgentPolicy).where(AgentPolicy.key == key,
                                  AgentPolicy.active.is_(True))
    ).scalar_one_or_none()
    if row is not None:
        return dict(row.value or {})
    return dict(policy_defaults().get(key, {}))


def set_policy(session: Any, key: str, value: dict[str, Any], *,
               user_id: int | None = None, note: str = "") -> AgentPolicy:
    """Write a new version. The previous one is kept, deactivated.

    Never an UPDATE. "What was the threshold when this case was created" is a
    question somebody asks in a review, and a row that was edited in place
    cannot answer it.
    """
    current = session.execute(
        select(AgentPolicy).where(AgentPolicy.key == key,
                                  AgentPolicy.active.is_(True))
    ).scalar_one_or_none()
    version = (current.version + 1) if current is not None else 1
    if current is not None:
        current.active = False

    row = AgentPolicy(key=key, version=version, value=dict(value),
                      description=POLICY_LABELS.get(key, key), active=True,
                      updated_by=user_id, note=note)
    session.add(row)
    session.flush()
    logger.info("policy '%s' now at version %s", key, version)
    return row


def history(session: Any, key: str) -> list[dict[str, Any]]:
    rows = list(session.execute(
        select(AgentPolicy).where(AgentPolicy.key == key)
        .order_by(AgentPolicy.version.desc())
    ).scalars().all())
    return [{"id": r.id, "key": r.key, "version": r.version,
             "value": dict(r.value or {}), "active": r.active,
             "note": r.note, "updated_by": r.updated_by,
             "at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


def policies(session: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for key in POLICY_KEYS:
        versions = history(session, key)
        active = next((v for v in versions if v["active"]), None)
        found.append({
            "key": key,
            "label": POLICY_LABELS.get(key, key),
            "value": active["value"] if active else policy_defaults().get(key, {}),
            "version": active["version"] if active else 0,
            "versions": len(versions),
            "history": versions[:10],
        })
    return found


__all__ = [
    "APPROVAL_POLICIES",
    "AUTONOMY",
    "AUTO_ASSIGN",
    "BUDGETS",
    "DAILY",
    "DRAFT_ONLY",
    "INTERVALS",
    "MANUAL",
    "MONTHLY",
    "NOTIFICATION",
    "ON_PUBLISH",
    "POLICY_KEYS",
    "POLICY_LABELS",
    "QUARTERLY",
    "RETENTION",
    "SCREENING",
    "SEEDS",
    "SEVERITY",
    "TRIGGERS",
    "TRIGGER_LABELS",
    "WEEKLY",
    "due",
    "fire",
    "history",
    "listing",
    "policies",
    "policy",
    "policy_defaults",
    "seed",
    "seed_policies",
    "set_enabled",
    "set_policy",
    "tick",
    "view",
]
