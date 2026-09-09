"""Changing a project that already exists, by saying so.

`draft.py` is the writer for a plan nobody has published yet. This is its
counterpart for one that is running: the same sentences, the same command
vocabulary, the same reader — landing on the real tables through
`backend.planner.service`.

Why a projection rather than a second reader
--------------------------------------------
`language.py` reads a sentence against a *plan document*: a dict with an
overview, governance, an agentic mode, milestones, tasks and links. A
published project holds exactly those facts in five tables. So the whole of
the difference between "edit the draft" and "edit the project" is one
function, `plan_of`, which renders the project in the shape the reader
already understands. There is no second grammar, no project-only phrasing,
and a rule added for drafts works here the day it is written.

Why every write goes through `service`
--------------------------------------
Nothing in this module writes a column. It resolves a code to a row id and
calls the same function the task drawer calls. That is what makes the
permission check, the history entry, the audit line, the optimistic-lock
bump and the re-evaluation signal identical whether a change arrived by
typing a sentence or by clicking a field — and it is why "the Copilot moved
a date it was not allowed to move" is not a failure this design can have.

What it will not do
-------------------
  * Remove a milestone. Nothing in the service layer deletes one, and a
    milestone with work under it is not something to destroy by saying so.
  * `set_step`. That is a draft's position in its own wizard; a running
    project does not have one.

Both refuse with a sentence rather than a stack trace, because a person who
asked for something reasonable deserves to be told which door it is behind.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    ENTITY_MILESTONE,
    ENTITY_TASK,
    SOURCE_AI_CHAT,
    PlannerDependency,
    PlannerMilestone,
    PlannerProject,
    PlannerTask,
)
from backend.planner import access as acl
from backend.planner import draft as dr
from backend.planner import policy as policy_mod
from backend.planner import service

LIVE_VERSION = "1.0.0"


class LiveError(ValueError):
    """Something a person asked for that this door does not open."""


# --------------------------------------------------------------- projection


def _iso(value: Any) -> str:
    return str(value) if value else ""


def plan_of(session: Any, principal: Any, project_id: int) -> dict[str, Any]:
    """A published project, in the plan shape the reader speaks.

    Read with the caller's permissions: `acl.readable` is what decides
    whether this project is theirs to see at all, and the projection carries
    nothing the project page would not show them.
    """
    acl.readable(session, int(project_id), principal)
    project = session.get(PlannerProject, int(project_id))

    milestones = list(session.execute(
        select(PlannerMilestone)
        .where(PlannerMilestone.project_id == int(project_id))
        .order_by(PlannerMilestone.code)).scalars())
    tasks = list(session.execute(
        select(PlannerTask)
        .where(PlannerTask.project_id == int(project_id))
        .order_by(PlannerTask.code)).scalars())
    links = list(session.execute(
        select(PlannerDependency)
        .where(PlannerDependency.project_id == int(project_id))).scalars())

    by_milestone = {int(m.id): str(m.code) for m in milestones}
    codes = {(ENTITY_MILESTONE, int(m.id)): str(m.code) for m in milestones}
    codes.update({(ENTITY_TASK, int(t.id)): str(t.code) for t in tasks})

    plan = dr.empty()
    plan["overview"] = {
        "name": str(project.name or ""), "code": str(project.code or ""),
        "description": str(project.description or ""),
        "objective": str(project.objective or "")}
    plan["governance"] = {
        "sponsor_id": project.sponsor_id, "manager_id": project.manager_id,
        "owner_id": project.owner_id, "escalation_id": project.escalation_id,
        "priority": str(project.priority or ""),
        "status": str(project.status or ""),
        "start_date": _iso(project.start_date),
        "target_end_date": _iso(project.target_end_date),
        "reporting_cadence": str(project.reporting_cadence or "")}
    plan["agentic"] = {"mode": str(project.agentic_mode or ""),
                       "policy": dict(project.agentic_policy or {})}
    plan["milestones"] = [
        {"code": str(row.code), "name": str(row.name or ""),
         "description": str(row.description or ""),
         "owner_id": row.owner_id, "escalation_id": row.escalation_id,
         "start_date": _iso(row.start_date),
         "target_date": _iso(row.target_date),
         "critical_date": _iso(row.critical_date)}
        for row in milestones]
    plan["tasks"] = [
        {"code": str(row.code), "title": str(row.title or ""),
         "description": str(row.description or ""),
         "milestone_code": by_milestone.get(int(row.milestone_id or 0), ""),
         "owner_id": row.owner_id, "escalation_id": row.escalation_id,
         "start_date": _iso(row.start_date), "due_date": _iso(row.due_date),
         "status": str(row.status or "")}
        for row in tasks]
    plan["links"] = [
        {"predecessor": codes.get((row.predecessor_type,
                                   int(row.predecessor_id)), ""),
         "successor": codes.get((row.successor_type, int(row.successor_id)),
                                ""),
         "type": str(row.dependency_type or "FS"),
         "lag_days": int(row.lag_days or 0)}
        for row in links
        if codes.get((row.predecessor_type, int(row.predecessor_id)))
        and codes.get((row.successor_type, int(row.successor_id)))]
    return plan


# ------------------------------------------------------------- finding rows


def _milestone(session: Any, project_id: int, code: str) -> PlannerMilestone:
    row = session.execute(
        select(PlannerMilestone).where(
            PlannerMilestone.project_id == int(project_id),
            PlannerMilestone.code == str(code or "").upper()),
    ).scalar_one_or_none()
    if row is None:
        raise LiveError(f"There is no milestone {code} on this project.")
    return row


def _task(session: Any, project_id: int, code: str) -> PlannerTask:
    row = session.execute(
        select(PlannerTask).where(
            PlannerTask.project_id == int(project_id),
            PlannerTask.code == str(code or "").upper()),
    ).scalar_one_or_none()
    if row is None:
        raise LiveError(f"There is no task {code} on this project.")
    return row


def _entity(session: Any, project_id: int, code: str) -> tuple[str, int]:
    """A code, as the kind and id a dependency is made of."""
    wanted = str(code or "").upper()
    milestone = session.execute(
        select(PlannerMilestone).where(
            PlannerMilestone.project_id == int(project_id),
            PlannerMilestone.code == wanted)).scalar_one_or_none()
    if milestone is not None:
        return ENTITY_MILESTONE, int(milestone.id)
    task = session.execute(
        select(PlannerTask).where(
            PlannerTask.project_id == int(project_id),
            PlannerTask.code == wanted)).scalar_one_or_none()
    if task is not None:
        return ENTITY_TASK, int(task.id)
    raise LiveError(f"There is nothing called {code} on this project.")


def _next_milestone_code(plan: dict[str, Any]) -> str:
    used = {str(m.get("code", "")).upper() for m in plan.get("milestones", [])}
    index = 1
    while dr.milestone_code(index) in used:
        index += 1
    return dr.milestone_code(index)


def _next_task_code(plan: dict[str, Any], milestone: str) -> str:
    used = {str(t.get("code", "")).upper() for t in plan.get("tasks", [])}
    index = 1
    while dr.task_code(milestone, index) in used:
        index += 1
    return dr.task_code(milestone, index)


def _fields(data: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    """Only what was actually said.

    A key that is absent means "leave it alone"; a key present and empty
    means "clear it". Passing everything through would turn "Rohan owns this"
    into "Rohan owns this and it has no dates", which is not what was said.
    """
    return {name: data[name] for name in names if name in data}


# ---------------------------------------------------------------- the writer


COMMANDS: tuple[str, ...] = (
    "set_overview", "set_governance", "set_agentic",
    "add_milestone", "update_milestone",
    "add_task", "update_task", "remove_task",
    "add_link", "remove_link",
)

#: Commands a draft has and a running project does not, each with the reason
#: rather than a shrug. Kept beside `COMMANDS` so the two cannot drift.
REFUSED: dict[str, str] = {
    "remove_milestone":
        "I will not delete a milestone off a running project — the work "
        "underneath it would be orphaned. Move the tasks first, then remove "
        "it on the Milestones tab.",
    "set_step":
        "That is a step in setting a plan up, and this project is already "
        "running.",
}


def apply(session: Any, principal: Any, project_id: int, command: str,
          payload: dict[str, Any] | None = None, *,
          source: str = SOURCE_AI_CHAT) -> dict[str, Any]:
    """One command against a live project, through the ordinary service layer."""
    verb = str(command or "").strip().lower()
    if verb in REFUSED:
        raise LiveError(REFUSED[verb])
    if verb not in COMMANDS:
        raise LiveError(
            f"I do not know how to {command!r} on a project that is already "
            "running.")
    data = dict(payload or {})
    return _COMMANDS[verb](session, principal, int(project_id), data, source)


def _cmd_overview(session: Any, principal: Any, project_id: int,
                  data: dict[str, Any], source: str) -> dict[str, Any]:
    fields = _fields(data, ("name", "description", "objective"))
    if not fields:
        return {"code": ""}
    project = service.update_project(session, principal, project_id,
                                     source=source, **fields)
    return {"code": str(project.code)}


_GOVERNANCE: tuple[str, ...] = (
    "sponsor_id", "manager_id", "owner_id", "escalation_id", "priority",
    "status", "start_date", "target_end_date", "reporting_cadence")


def _cmd_governance(session: Any, principal: Any, project_id: int,
                    data: dict[str, Any], source: str) -> dict[str, Any]:
    fields = _fields(data, _GOVERNANCE)
    if not fields:
        return {"code": ""}
    project = service.update_project(session, principal, project_id,
                                     source=source, **fields)
    return {"code": str(project.code)}


def _cmd_agentic(session: Any, principal: Any, project_id: int,
                 data: dict[str, Any], source: str) -> dict[str, Any]:
    mode = str(data.get("mode") or "").upper()
    document = data.get("policy")
    # Resolved before it is stored, so an incoherent custom policy is refused
    # with the sentence `policy` writes rather than accepted and then obeyed.
    agentic = policy_mod.resolve(mode, document)
    project = service.update_project(
        session, principal, project_id, source=source,
        agentic_mode=agentic.mode, agentic_policy=document)
    actor = getattr(principal, "user_id", None)
    service.audit(session, "PLANNER_AGENTIC_SET", actor_id=actor,
                  project_id=int(project_id), source=source,
                  mode=agentic.mode)
    return {"code": str(project.code), "mode": agentic.mode}


_MILESTONE_FIELDS: tuple[str, ...] = (
    "name", "description", "owner_id", "escalation_id", "start_date",
    "target_date", "critical_date", "priority", "status")


def _cmd_add_milestone(session: Any, principal: Any, project_id: int,
                       data: dict[str, Any], source: str) -> dict[str, Any]:
    plan = plan_of(session, principal, project_id)
    code = str(data.get("code") or "").upper() or _next_milestone_code(plan)
    row = service.create_milestone(
        session, principal, project_id, code=code,
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        owner_id=data.get("owner_id"),
        escalation_id=data.get("escalation_id"),
        start_date=data.get("start_date") or None,
        target_date=data.get("target_date") or None,
        critical_date=data.get("critical_date") or None,
        source=source)
    session.flush()
    return {"code": str(row.code)}


def _cmd_update_milestone(session: Any, principal: Any, project_id: int,
                          data: dict[str, Any], source: str) -> dict[str, Any]:
    row = _milestone(session, project_id, str(data.get("code") or ""))
    fields = _fields(data, _MILESTONE_FIELDS)
    if fields:
        service.update_milestone(session, principal, int(row.id),
                                 source=source, **fields)
    return {"code": str(row.code)}


_TASK_FIELDS: tuple[str, ...] = (
    "title", "description", "owner_id", "escalation_id", "start_date",
    "due_date", "critical_date", "priority", "status", "percent_complete",
    "blocked", "blocker_reason", "next_step")


def _cmd_add_task(session: Any, principal: Any, project_id: int,
                  data: dict[str, Any], source: str) -> dict[str, Any]:
    plan = plan_of(session, principal, project_id)
    parent = str(data.get("milestone_code") or "").upper()
    if not parent:
        raise LiveError(
            "Which milestone does that go under? A task with no milestone on "
            "a running project has nobody answerable for the date.")
    milestone = _milestone(session, project_id, parent)
    code = str(data.get("code") or "").upper() or _next_task_code(plan, parent)
    row = service.create_task(
        session, principal, project_id, code=code,
        milestone_id=int(milestone.id),
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        owner_id=data.get("owner_id"),
        escalation_id=data.get("escalation_id"),
        start_date=data.get("start_date") or None,
        due_date=data.get("due_date") or None,
        source=source)
    session.flush()
    return {"code": str(row.code)}


def _cmd_update_task(session: Any, principal: Any, project_id: int,
                     data: dict[str, Any], source: str) -> dict[str, Any]:
    row = _task(session, project_id, str(data.get("code") or ""))
    fields = _fields(data, _TASK_FIELDS)
    if "milestone_code" in data and data["milestone_code"]:
        fields["milestone_id"] = int(
            _milestone(session, project_id, str(data["milestone_code"])).id)
    if fields:
        service.update_task(session, principal, int(row.id), source=source,
                            **fields)
    return {"code": str(row.code)}


def _cmd_remove_task(session: Any, principal: Any, project_id: int,
                     data: dict[str, Any], source: str) -> dict[str, Any]:
    row = _task(session, project_id, str(data.get("code") or ""))
    code = str(row.code)
    service.delete_task(session, principal, int(row.id), source=source)
    return {"code": code}


def _cmd_add_link(session: Any, principal: Any, project_id: int,
                  data: dict[str, Any], source: str) -> dict[str, Any]:
    before = str(data.get("predecessor") or "")
    after = str(data.get("successor") or "")
    pred_kind, pred_id = _entity(session, project_id, before)
    succ_kind, succ_id = _entity(session, project_id, after)
    service.create_dependency(
        session, principal, project_id,
        predecessor_type=pred_kind, predecessor_id=pred_id,
        successor_type=succ_kind, successor_id=succ_id,
        dependency_type=str(data.get("type") or "FS"),
        lag_days=int(data.get("lag_days") or 0), source=source)
    return {"code": after.upper()}


def _cmd_remove_link(session: Any, principal: Any, project_id: int,
                     data: dict[str, Any], source: str) -> dict[str, Any]:
    pred_kind, pred_id = _entity(session, project_id,
                                 str(data.get("predecessor") or ""))
    succ_kind, succ_id = _entity(session, project_id,
                                 str(data.get("successor") or ""))
    row = session.execute(
        select(PlannerDependency).where(
            PlannerDependency.project_id == int(project_id),
            PlannerDependency.predecessor_type == pred_kind,
            PlannerDependency.predecessor_id == pred_id,
            PlannerDependency.successor_type == succ_kind,
            PlannerDependency.successor_id == succ_id)).scalar_one_or_none()
    if row is None:
        raise LiveError("Those two are not linked, so there is nothing to "
                        "unlink.")
    service.delete_dependency(session, principal, int(row.id), source=source)
    return {"code": str(data.get("successor") or "").upper()}


_COMMANDS = {
    "set_overview": _cmd_overview,
    "set_governance": _cmd_governance,
    "set_agentic": _cmd_agentic,
    "add_milestone": _cmd_add_milestone,
    "update_milestone": _cmd_update_milestone,
    "add_task": _cmd_add_task,
    "update_task": _cmd_update_task,
    "remove_task": _cmd_remove_task,
    "add_link": _cmd_add_link,
    "remove_link": _cmd_remove_link,
}


# ------------------------------------------------------------- a whole turn


def apply_all(session: Any, principal: Any, project_id: int,
              proposals: list[Any], *,
              source: str = SOURCE_AI_CHAT) -> dict[str, Any]:
    """Every command from one sentence, in order, against a live project.

    The mirror of `language.apply_all`, and deliberately the same shape: the
    `$new:` placeholders an earlier command created are substituted into the
    later ones, so "add a milestone and put two tasks under it" is one turn
    here exactly as it is on a draft.
    """
    from backend.planner import language as lang

    made: dict[str, str] = {}
    outcomes: list[dict[str, Any]] = []
    for proposal in proposals:
        payload = {k: (made.get(v, v)
                       if isinstance(v, str) and v.startswith(lang.PENDING)
                       else v)
                   for k, v in proposal.payload.items()}
        unfilled = [v for v in payload.values()
                    if isinstance(v, str) and v.startswith(lang.PENDING)]
        if unfilled:
            raise LiveError(
                "I lost track of something I was about to create. Say that "
                "again and I will start from what is on the project now.")
        outcome = apply(session, principal, project_id, proposal.command,
                        payload, source=source)
        code = str(outcome.get("code") or "")
        if getattr(proposal, "creates", "") and code:
            made[proposal.creates] = code
        outcomes.append({"command": proposal.command,
                         "sentence": proposal.sentence,
                         "code": code, "outcome": outcome})
    return {"applied": outcomes, "created": made}


__all__ = [
    "COMMANDS", "LIVE_VERSION", "LiveError", "REFUSED", "apply", "apply_all",
    "plan_of",
]
