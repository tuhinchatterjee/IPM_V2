"""
Persisting an agentic run. §19.

Everything §19 lists ends up in `agent_runs` and `agent_tasks`, and this module
is the only thing that writes them. Two properties follow from that and both
matter:

**A run is observable while it is running.** The stage, the specialists and the
task statuses are written as they change, not assembled at the end. That is what
makes the working indicator show real progress rather than a timer, and it is
what makes a run that died mid-flight readable afterwards — the last stage it
reached is on the row.

**A run is readable months later.** The plan, the budgets, the data versions,
the registry fingerprint and the build SHA are stored *as they were*, so a run
can be read against the definitions that actually governed it rather than
against today's.

Sessions
--------
Every function takes a session. The orchestrator runs inside a worker that owns
its transaction boundaries, and a store that opened its own connections would
commit a stage change inside a transaction the caller was about to roll back.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend.agentic import stages
from backend.models.platform import AgentRun, AgentTask

logger = logging.getLogger(__name__)

# Triggers.
USER_QUESTION = "user_question"
SCHEDULED_REVIEW = "scheduled_review"
EVENT = "event"
MANUAL_REVIEW = "manual_review"

TRIGGERS: tuple[str, ...] = (USER_QUESTION, SCHEDULED_REVIEW, EVENT,
                             MANUAL_REVIEW)

TRIGGER_LABELS: dict[str, str] = {
    USER_QUESTION: "A question was asked",
    SCHEDULED_REVIEW: "A governed schedule fired",
    EVENT: "Newly published data",
    MANUAL_REVIEW: "A review was requested",
}

#: The identity a proactive run acts as. §57: a scheduled review is not
#: "nobody" — it is a principal whose data permissions are its own, and every
#: row it reads is attributed to it.
SERVICE_IDENTITY = "creditprobe.review"


def _now() -> datetime:
    return datetime.now(UTC)


def _key() -> str:
    return f"ar_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------


def start(session: Any, *, trigger: str, question: str = "",
          period: str = "", prior_period: str = "",
          user_id: int | None = None, role: str = "",
          service_identity: str = "", project_id: int | None = None,
          investigation_id: int | None = None, event_id: int | None = None,
          trigger_object_type: str = "", trigger_object_id: str = "",
          selection: Any = None, budget: Any = None,
          versions: dict[str, Any] | None = None) -> AgentRun:
    """Create the run row, before anything runs.

    Created first, deliberately. A run that exists only once it succeeds cannot
    show a user what is happening, and cannot be found afterwards if it never
    finished — which is precisely the run somebody wants to look at.
    """
    from backend.agentic import registry

    chosen = selection.to_dict() if selection is not None else {}
    run = AgentRun(
        run_key=_key(),
        trigger=trigger,
        trigger_object_type=trigger_object_type,
        trigger_object_id=str(trigger_object_id or ""),
        event_id=event_id,
        question=question or "",
        period=period or "",
        prior_period=prior_period or "",
        user_id=user_id,
        service_identity=service_identity or (
            SERVICE_IDENTITY if trigger != USER_QUESTION else ""),
        role=role or "",
        project_id=project_id,
        investigation_id=investigation_id,
        officer_level=int(chosen.get("officer_level") or 1),
        officer_title=str(chosen.get("officer_title") or ""),
        selection_reason=str(chosen.get("selection_reason") or ""),
        complexity_score=int(chosen.get("complexity_score") or 0),
        risk_score=int(chosen.get("risk_score") or 0),
        agent_count=int(chosen.get("agent_count") or 0),
        planned_task_count=int(chosen.get("planned_task_count") or 0),
        status="queued",
        stage=stages.QUEUED,
        stage_history=[stages.step(stages.QUEUED).to_dict()],
        budgets=budget.to_dict() if budget is not None else {},
        versions={**_versions(), **(versions or {})},
        build_sha=_build_sha(),
        config_fingerprint=registry.fingerprint(),
        started_at=_now(),
    )
    session.add(run)
    session.flush()
    logger.info("agentic run %s started (%s, officer %s)", run.id, trigger,
                run.officer_title or "unset")
    return run


def _versions() -> dict[str, Any]:
    """Which governed definitions this run ran under.

    Recorded at the start rather than looked up at read time: a run read next
    year against today's ontology would be read against a definition it never
    used.
    """
    found: dict[str, Any] = {}
    try:
        from backend.semantics import ontology

        found["ontology"] = ontology.fingerprint()
    except Exception:  # noqa: BLE001 - a missing version is not a failed run
        logger.debug("ontology fingerprint unavailable", exc_info=True)
    try:
        from backend.agentic import registry, severity

        found["agent_registry"] = registry.fingerprint()
        found["severity_formula"] = severity.VERSION
    except Exception:  # noqa: BLE001
        logger.debug("agent registry fingerprint unavailable", exc_info=True)
    return found


def _build_sha() -> str:
    try:
        from backend.build_info import build_info

        return str(build_info().sha or "")[:64]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def advance(session: Any, run: AgentRun, stage: str, *, detail: str = "",
            agents: int = 0, nested: bool = False) -> bool:
    """Move to a stage, recording when.

    Refuses to move backwards (see `stages.can_move`) rather than silently
    accepting it: a run that shows VALIDATING and then SCOPING again has told
    the user something untrue, and the bug that caused it is easier to find
    here than in the transcript of somebody's demonstration.

    `nested=True` is for a stage report coming from INSIDE a later stage — a
    specialist running its own calculation while the run is COORDINATING.
    That is not a regression and it is not a lie: the run really is
    coordinating, and a specialist really is calculating. So the stage holds
    and the report is recorded as detail, which is what the screen should
    say. Without this the orchestrator's per-specialist reports each tried
    to move the run backwards and were refused with a warning apiece.
    """
    if not stages.can_move(run.stage or stages.QUEUED, stage):
        if nested and run.stage not in stages.TERMINAL:
            history = list(run.stage_history or [])
            history.append(stages.step(
                run.stage, agents=agents,
                detail=detail or stages.caption(stage)).to_dict())
            run.stage_history = history
            run.updated_at = _now()
            session.flush()
            return True
        logger.warning("run %s refused stage %s → %s", run.id, run.stage,
                       stage)
        return False

    run.stage = stage
    run.status = _status_for(stage)
    history = list(run.stage_history or [])
    history.append(stages.step(stage, detail=detail, agents=agents).to_dict())
    run.stage_history = history
    run.updated_at = _now()
    session.flush()
    return True


def _status_for(stage: str) -> str:
    if stage == stages.COMPLETE:
        return "complete"
    if stage == stages.FAILED:
        return "failed"
    if stage == stages.NEEDS_INPUT:
        return "needs_input"
    if stage == stages.CANCELLED:
        return "cancelled"
    if stage == stages.QUEUED:
        return "queued"
    return stage.lower()


def record_plan(session: Any, run: AgentRun, plan: Any, *,
                orchestrator: str = "", specialists: list[str] | None = None,
                selection: Any = None) -> list[AgentTask]:
    """Write the plan and its tasks.

    The whole DAG is written in one flush, so a run never exists with half a
    plan — a half-written plan read by the Runs tab looks like a run that
    decided to do less than it did.
    """
    run.plan = {"objective": plan.objective, "scope": dict(plan.scope),
                "rationale": plan.rationale}
    run.task_graph = plan.to_dict()
    run.orchestrator = orchestrator or run.orchestrator
    names = list(specialists or plan.agents)
    run.specialists = names
    run.agent_count = len(names)
    run.planned_task_count = len(plan.tasks)
    if selection is not None:
        chosen = selection.to_dict()
        run.officer_level = int(chosen.get("officer_level") or run.officer_level)
        run.officer_title = str(chosen.get("officer_title")
                                or run.officer_title)
        run.selection_reason = str(chosen.get("selection_reason")
                                   or run.selection_reason)
        run.complexity_score = int(chosen.get("complexity_score") or 0)
        run.risk_score = int(chosen.get("risk_score") or 0)

    rows: list[AgentTask] = []
    for task in plan.tasks:
        row = AgentTask(
            run_id=run.id, task_key=task.task_key, agent_id=task.agent_id,
            purpose=task.purpose, depends_on=list(task.depends_on),
            layer=task.layer, tool=task.tool,
            parameters=dict(task.parameters), inputs=dict(task.inputs),
            status=task.status)
        session.add(row)
        rows.append(row)
    session.flush()
    return rows


def update_task(session: Any, run_id: int, task: Any) -> None:
    """Write one task's state back."""
    row = session.execute(
        select(AgentTask).where(AgentTask.run_id == run_id,
                                AgentTask.task_key == task.task_key)
    ).scalar_one_or_none()
    if row is None:
        return

    row.status = task.status
    row.layer = task.layer
    row.analysis_run_id = task.analysis_run_id
    row.result = dict(task.result or {})
    row.finding = task.finding or ""
    row.evidence = dict(task.evidence or {})
    row.validation_state = task.validation_state
    row.validation = dict(task.validation or {})
    row.tool_calls = list(task.tool_calls or [])
    row.data_versions = dict(task.data_versions or {})
    row.retry_count = int(task.retry_count or 0)
    row.error_category = (task.error_category or "")[:48]
    row.error = task.error or ""
    row.approval_state = task.approval_state
    row.duration_ms = int(task.duration_ms or 0)
    if task.status == "running" and row.started_at is None:
        row.started_at = _now()
    if task.finished and row.completed_at is None:
        row.completed_at = _now()
    session.flush()


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------


def finish(session: Any, run: AgentRun, *, plan: Any = None,
           findings: list[dict[str, Any]] | None = None,
           conflicts: list[Any] | None = None,
           handoffs: list[Any] | None = None,
           validation: dict[str, Any] | None = None,
           assurance: Any = None, synthesis: str = "",
           budget: Any = None, analysis_run_id: int | None = None,
           trace_id: str = "", cases: list[int] | None = None) -> AgentRun:
    """Complete a run and write everything it produced."""
    if plan is not None:
        run.task_graph = plan.to_dict()
    run.findings = list(findings or [])
    run.conflicts = [c.to_dict() if hasattr(c, "to_dict") else dict(c)
                     for c in (conflicts or [])]
    run.handoffs = [h.to_dict() if hasattr(h, "to_dict") else dict(h)
                    for h in (handoffs or [])]
    run.validation = dict(validation or {})
    run.assurance = assurance.to_dict() if assurance is not None else {}
    run.synthesis = synthesis or ""
    if budget is not None:
        run.budgets = budget.to_dict()
        run.usage = {"spent": dict(budget.spent),
                     "line": budget.usage_line()}
    if analysis_run_id:
        run.analysis_run_id = analysis_run_id
    if trace_id:
        run.trace_id = trace_id
    if cases:
        detail = dict(run.plan or {})
        detail["cases_created"] = list(cases)
        run.plan = detail

    run.finished_at = _now()
    if run.started_at is not None:
        run.duration_ms = int(
            (run.finished_at - run.started_at).total_seconds() * 1000)
    advance(session, run, stages.COMPLETE)
    session.flush()
    logger.info("agentic run %s complete in %sms", run.id, run.duration_ms)
    return run


def fail(session: Any, run: AgentRun, *, reason: str, kind: str = "",
         plan: Any = None, budget: Any = None,
         findings: list[dict[str, Any]] | None = None) -> AgentRun:
    """Stop a run and say why.

    §55: what completed is preserved. A run that failed on its fourth task
    still has three results worth reading, and discarding them because the
    fourth failed is throwing away the work the user paid for.
    """
    run.failure = reason
    run.failure_kind = (kind or "")[:48]
    if plan is not None:
        run.task_graph = plan.to_dict()
    if findings is not None:
        run.findings = list(findings)
    if budget is not None:
        run.budgets = budget.to_dict()
        run.usage = {"spent": dict(budget.spent), "line": budget.usage_line()}
    run.finished_at = _now()
    if run.started_at is not None:
        run.duration_ms = int(
            (run.finished_at - run.started_at).total_seconds() * 1000)
    advance(session, run, stages.FAILED, detail=reason[:160])
    session.flush()
    return run


def cancelled(session: Any, run: AgentRun, *, plan: Any = None,
              reason: str = "Stopped at your request.") -> AgentRun:
    if plan is not None:
        run.task_graph = plan.to_dict()
    run.failure = reason
    run.failure_kind = "cancelled"
    run.finished_at = _now()
    advance(session, run, stages.CANCELLED, detail=reason)
    session.flush()
    return run


def needs_input(session: Any, run: AgentRun, *, question: str) -> AgentRun:
    run.failure = question
    run.failure_kind = "needs_input"
    advance(session, run, stages.NEEDS_INPUT, detail=question[:160])
    session.flush()
    return run


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load(session: Any, run_id: int) -> AgentRun | None:
    return session.get(AgentRun, run_id)


def by_key(session: Any, run_key: str) -> AgentRun | None:
    return session.execute(
        select(AgentRun).where(AgentRun.run_key == run_key)
    ).scalar_one_or_none()


def tasks_of(session: Any, run_id: int) -> list[AgentTask]:
    return list(session.execute(
        select(AgentTask).where(AgentTask.run_id == run_id)
        .order_by(AgentTask.layer, AgentTask.id)
    ).scalars().all())


def for_analysis(session: Any, analysis_run_id: int) -> AgentRun | None:
    """The agentic run behind an analysis, if one produced it.

    Looked up two ways because an agentic run relates to an analysis in two
    ways: it may have recorded that analysis as its own primary result, or one
    of its delegated tasks may have produced it. The Trace has to find the
    coordination from either end.
    """
    from backend.models.platform import AgentTask

    found = session.execute(
        select(AgentRun).where(AgentRun.analysis_run_id == analysis_run_id)
        .order_by(AgentRun.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if found is not None:
        return found

    run_id = session.execute(
        select(AgentTask.run_id)
        .where(AgentTask.analysis_run_id == analysis_run_id)
        .order_by(AgentTask.id.desc()).limit(1)
    ).scalar()
    return session.get(AgentRun, run_id) if run_id else None


def story(session: Any, run: AgentRun) -> list[dict[str, Any]]:
    """§27's Trace Story for an agentic run.

    Six stages, each a paragraph a reader can take in without clicking a node:

        TRIGGERED     why CreditProbe acted
        ORCHESTRATED  which officer, and which specialists
        INVESTIGATED  what was actually run
        VALIDATED     what Assurance checked
        DECIDED       what was concluded
        ACTIONED      what was created

    Assembled from the run's own record — the stage history, the task rows, the
    validation document — rather than written, so a story and the graph beside
    it cannot disagree.
    """
    from backend.agentic import registry

    tasks = tasks_of(session, run.id)
    done = [t for t in tasks if t.status == "complete"]
    checked = [t for t in tasks if t.validation_state != "not_required"]
    specialists = [registry.agent(a).business_name
                   for a in (run.specialists or []) if registry.agent(a)]
    cases = list((run.plan or {}).get("cases_created") or [])

    found: list[dict[str, Any]] = [
        {
            "stage": "TRIGGERED",
            "title": TRIGGER_LABELS.get(run.trigger, run.trigger),
            "body": (run.question or
                     f"A review of {run.period}." if run.period else
                     "CreditProbe was asked to act."),
            "detail": (f"Service identity {run.service_identity}."
                       if run.service_identity else ""),
        },
        {
            "stage": "ORCHESTRATED",
            "title": f"{run.officer_title or 'CreditProbe'} took the request",
            "body": run.selection_reason
                    or "No structural reason was recorded.",
            "detail": (f"{len(specialists)} specialists: "
                       f"{' · '.join(specialists)}." if specialists else ""),
        },
        {
            "stage": "INVESTIGATED",
            "title": (f"{len(done)} governed "
                      f"{'analysis' if len(done) == 1 else 'analyses'}"),
            "body": "; ".join(t.finding for t in done if t.finding)
                    or "Nothing was computed.",
            "detail": "; ".join(
                f"{t.agent_id}: {t.purpose}" for t in done[:4]),
        },
        {
            "stage": "VALIDATED",
            "title": ("Checked by Validation & Assurance" if checked
                      else "Nothing required checking"),
            "body": next((t.finding for t in tasks
                          if t.agent_id == registry.VALIDATION.agent_id
                          and t.finding), "No assurance pass was recorded."),
            "detail": (run.assurance or {}).get("status", ""),
        },
        {
            "stage": "DECIDED",
            "title": "What CreditProbe concluded",
            "body": run.synthesis or run.failure
                    or "No conclusion was recorded.",
            "detail": "; ".join(
                str(c.get("sentence") or "") for c in (run.conflicts or [])),
        },
        {
            "stage": "ACTIONED",
            "title": (f"{len(cases)} Risk "
                      f"{'Case' if len(cases) == 1 else 'Cases'} raised"
                      if cases else "An answer, and nothing else"),
            "body": (f"Cases {', '.join(str(c) for c in cases)} were created "
                     f"as drafts for a person to triage." if cases else
                     "Nothing was created; the answer is the outcome."),
            "detail": "",
        },
    ]
    return found


def listing(session: Any, *, limit: int = 40, status: str = "",
            trigger: str = "", user_id: int | None = None
            ) -> list[dict[str, Any]]:
    """Runs, most recent first. The Runs tab's list. §30."""
    query = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
    if status:
        query = query.where(AgentRun.status == status)
    if trigger:
        query = query.where(AgentRun.trigger == trigger)
    if user_id is not None:
        query = query.where(AgentRun.user_id == user_id)
    return [summary(r) for r in session.execute(query).scalars().all()]


def summary(run: AgentRun) -> dict[str, Any]:
    """One run, as a list row. §30's fields."""
    return {
        "id": run.id,
        "run_key": run.run_key,
        "trigger": run.trigger,
        "trigger_label": TRIGGER_LABELS.get(run.trigger, run.trigger),
        "question": run.question,
        "period": run.period,
        "officer_level": run.officer_level,
        "officer_title": run.officer_title,
        "orchestrator": run.orchestrator,
        "specialists": list(run.specialists or []),
        "agent_count": run.agent_count,
        "task_count": run.planned_task_count,
        "status": run.status,
        "stage": run.stage,
        "stage_label": stages.SHORT.get(run.stage, run.stage),
        "assurance": (run.assurance or {}).get("status", ""),
        "usage": (run.usage or {}).get("line", ""),
        "failure": run.failure,
        "failure_kind": run.failure_kind,
        "analysis_run_id": run.analysis_run_id,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "duration_ms": run.duration_ms,
        "created_at": _iso(run.created_at),
    }


def detail(session: Any, run: AgentRun) -> dict[str, Any]:
    """One run in full, for the Trace and the Runs tab's detail view."""
    task_rows = tasks_of(session, run.id)
    found = summary(run)
    found.update({
        "selection_reason": run.selection_reason,
        "complexity_score": run.complexity_score,
        "risk_score": run.risk_score,
        "plan": dict(run.plan or {}),
        "task_graph": dict(run.task_graph or {}),
        "budgets": dict(run.budgets or {}),
        "versions": dict(run.versions or {}),
        "findings": list(run.findings or []),
        "conflicts": list(run.conflicts or []),
        "handoffs": list(run.handoffs or []),
        "validation": dict(run.validation or {}),
        "assurance_detail": dict(run.assurance or {}),
        "synthesis": run.synthesis,
        "stage_history": list(run.stage_history or []),
        "trace_id": run.trace_id,
        "build_sha": run.build_sha,
        "config_fingerprint": run.config_fingerprint,
        "service_identity": run.service_identity,
        "project_id": run.project_id,
        "investigation_id": run.investigation_id,
        "tasks": [_task_view(t) for t in task_rows],
    })
    return found


def _task_view(row: AgentTask) -> dict[str, Any]:
    from backend.agentic import registry

    agent = registry.agent(row.agent_id)
    return {
        "task_key": row.task_key,
        "agent_id": row.agent_id,
        "agent_name": agent.business_name if agent else row.agent_id,
        "purpose": row.purpose,
        "depends_on": list(row.depends_on or []),
        "layer": row.layer,
        "tool": row.tool,
        "status": row.status,
        "analysis_run_id": row.analysis_run_id,
        "finding": row.finding,
        "evidence": dict(row.evidence or {}),
        "validation_state": row.validation_state,
        "validation": dict(row.validation or {}),
        "tool_calls": list(row.tool_calls or []),
        "retry_count": row.retry_count,
        "error": row.error,
        "error_category": row.error_category,
        "approval_state": row.approval_state,
        "duration_ms": row.duration_ms,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def live(session: Any, run_id: int) -> dict[str, Any] | None:
    """What the working indicator polls. §8.

    Deliberately small: the stage, the officer, the specialists and the elapsed
    time. The full run document is several kilobytes and nothing on screen
    while a request is in flight needs it.
    """
    run = load(session, run_id)
    if run is None:
        return None
    elapsed = 0
    if run.started_at is not None:
        end = run.finished_at or _now()
        elapsed = int((end - run.started_at).total_seconds() * 1000)
    last = (run.stage_history or [{}])[-1]
    return {
        "run_id": run.id,
        "run_key": run.run_key,
        **stages.view(
            run.stage or stages.QUEUED,
            history=list(run.stage_history or []),
            detail=str(last.get("detail") or ""),
            agents=run.agent_count,
            officer=run.officer_title,
            specialists=list(run.specialists or []),
            elapsed_ms=elapsed),
        "officer_level": run.officer_level,
        "selection_reason": run.selection_reason,
        "escalation_line": (run.plan or {}).get("escalation_line", ""),
        "failure": run.failure,
        "assurance": (run.assurance or {}).get("status", ""),
        "analysis_run_id": run.analysis_run_id,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


__all__ = [
    "EVENT",
    "MANUAL_REVIEW",
    "SCHEDULED_REVIEW",
    "SERVICE_IDENTITY",
    "TRIGGERS",
    "TRIGGER_LABELS",
    "USER_QUESTION",
    "advance",
    "by_key",
    "cancelled",
    "detail",
    "fail",
    "finish",
    "listing",
    "live",
    "load",
    "needs_input",
    "record_plan",
    "start",
    "summary",
    "tasks_of",
    "update_task",
]
