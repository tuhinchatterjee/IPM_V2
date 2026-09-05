"""The small set of things a person may change by saying so.

Until now the Project Planner's agent was read-only apart from drafting the
text of a chase. That is the safe default and most of it stays: there is still
no registered capability that completes a task, moves a due date, changes an
owner, cancels work, closes a risk or sets a project's health, and those six
names are still in `NO_TOOL_EXISTS`.

What this module adds is the narrow band where refusing is worse than
allowing. "Update Data Mapping to 80%, no blocker, expect Friday" is a person
reporting on their own work in their own words. Making them open a screen to
type it into three boxes is not governance, it is friction — and friction is
why status reports go stale, which is the thing this whole feature exists to
prevent.

Three rules make that safe:

**It goes through the service, never around it.** Every function here calls
`service.update_task` or `service.create_raid`, which means the same
permission check, the same version bump, the same immutable history row and
the same audit record as the screen. There is no second write path to keep in
step.

**The human is the actor.** `principal` is the person who typed the sentence,
not a service identity. The history row carries their id; the audit record
carries their name. "The AI changed it" is never what the record says, because
it is never what happened.

**SOURCE is AI_CHAT.** Distinct from `AI`, which means an agent acted on its
own. A reviewer looking at a project's history can tell the three apart:
somebody typed it into a screen, somebody said it in conversation, or the
system worked it out.

Commitments stay where they were. A due date, an owner, a cancellation and a
health override are changes to what was promised rather than reports on it,
and they are unreachable from here — not by a check that has to be written
correctly, but because no function in this module can express them.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    SOURCE_AI_CHAT,
    PlannerTask,
)
from backend.planner import access as acl
from backend.planner import service as svc

logger = logging.getLogger(__name__)

ACTIONS_VERSION = "1.0.0"

#: What a person may change by saying so. Written down here as well as in the
#: registry, because "what can conversation change?" is a question somebody
#: asks about this file, not about the tool table.
CONVERSATIONAL = (
    "report progress on a task you can update",
    "say that a task is blocked, and why",
    "say that a task is no longer blocked",
    "raise a risk, issue, assumption or decision",
)

#: And what it may not, in the same words the refusal uses.
NEVER_CONVERSATIONAL = (
    "complete a task", "change a task's owner", "move a due date",
    "cancel a task", "close a risk", "set a project's health",
)


class Refused(PermissionError):
    """Asked for something conversation is not allowed to do."""


def _task(session: Any, principal: Any, project_id: int, code: str) -> Any:
    """Find a task by its code within one project.

    By code rather than by id, because a person says "T-104" and not "task
    8,317". Scoped to the project first so a code that exists on somebody
    else's project is not found here.
    """
    acl.readable(session, project_id, principal)
    wanted = str(code or "").strip()
    if not wanted:
        raise svc.PlannerError("Which task? Give its code, such as T-104.")
    row = session.execute(
        select(PlannerTask).where(
            PlannerTask.project_id == int(project_id),
            PlannerTask.code == wanted)).scalar_one_or_none()
    if row is None:
        raise svc.PlannerError(
            f"This project has no task called {wanted}.")
    return row


def _guard_commitments(**fields: Any) -> None:
    """Refuse a commitment change however it arrived.

    Belt and braces: no caller in this module passes these, and the functions
    have no parameters for them. This exists so that a future edit which adds
    a `**kwargs` passthrough — the way these things actually happen — fails
    loudly instead of quietly widening what conversation can do.
    """
    forbidden = {"owner_id", "due_date", "start_date", "reviewer_id",
                 "status", "critical", "weight", "code"} & {
        k for k, v in fields.items() if v is not None}
    if forbidden:
        raise Refused(
            "Changing " + ", ".join(sorted(forbidden)) + " is a change to a "
            "commitment rather than a report on one, so it is not something "
            "CreditProbe will do from a conversation. Open the task and "
            "change it there, where the change is yours and recorded as "
            "yours.")


def post_task_update(session: Any, principal: Any, project_id: int, *,
                     code: str, percent_complete: int | None = None,
                     narrative: str = "", next_step: str = "",
                     blocked: bool | None = None,
                     blocker_reason: str = "") -> dict[str, Any]:
    """Report progress on a task, in the reporter's own words.

    Progress, a sentence, a next step and the blocked flag — the same four
    fields the quick-update drawer offers, and for the same reason: they are
    what a person knows about their own work. Status is not among them; a task
    moving to COMPLETED is a claim somebody should make deliberately.
    """
    _guard_commitments(percent=None)
    task = _task(session, principal, project_id, code)
    before = {"percent_complete": int(task.percent_complete or 0),
              "blocked": bool(task.blocked), "status": task.status}

    fields: dict[str, Any] = {}
    if percent_complete is not None:
        fields["percent_complete"] = int(percent_complete)
    if next_step:
        fields["next_step"] = next_step
    if blocked is not None:
        fields["blocked"] = bool(blocked)
        # Unblocking clears the reason; leaving the old one behind reads as
        # "still waiting on Legal" beside a task that is not waiting.
        fields["blocker_reason"] = blocker_reason if blocked else ""
    elif blocker_reason:
        fields["blocked"] = True
        fields["blocker_reason"] = blocker_reason

    if not fields and not narrative:
        raise svc.PlannerError(
            "There is nothing to record: say the progress, the blocker or "
            "what happens next.")

    updated = svc.update_task(session, principal, int(task.id),
                              narrative=narrative, source=SOURCE_AI_CHAT,
                              **fields)
    return {
        "applied": True, "task_code": updated.code, "task_id": int(updated.id),
        "project_id": int(updated.project_id),
        "was": before,
        "now": {"percent_complete": int(updated.percent_complete or 0),
                "blocked": bool(updated.blocked), "status": updated.status},
        "source": SOURCE_AI_CHAT,
        "recorded_for": getattr(principal, "user_id", None),
    }


def set_task_blocker(session: Any, principal: Any, project_id: int, *,
                     code: str, reason: str = "",
                     clear: bool = False) -> dict[str, Any]:
    """Say what a task is waiting for, or that it is no longer waiting.

    A blocker with no reason is refused by the service, which is right: it
    tells a project manager nothing they can act on. So is clearing one that
    was never set — silently succeeding would tell somebody they had fixed
    something they had not touched.
    """
    task = _task(session, principal, project_id, code)
    if clear:
        if not task.blocked:
            raise svc.PlannerError(f"{task.code} is not blocked.")
        updated = svc.update_task(
            session, principal, int(task.id), blocked=False,
            blocker_reason="", source=SOURCE_AI_CHAT,
            narrative="No longer blocked.")
        return {"applied": True, "task_code": updated.code,
                "blocked": False, "source": SOURCE_AI_CHAT}

    if not str(reason or "").strip():
        raise svc.PlannerError(
            "A blocked task needs a reason. What is it waiting for, and who "
            "owes it?")
    updated = svc.update_task(
        session, principal, int(task.id), blocked=True,
        blocker_reason=reason, source=SOURCE_AI_CHAT,
        narrative=f"Blocked: {reason}")
    return {"applied": True, "task_code": updated.code, "blocked": True,
            "reason": updated.blocker_reason, "source": SOURCE_AI_CHAT}


def create_raid_item(session: Any, principal: Any, project_id: int, *,
                     title: str, raid_type: str = "RISK",
                     severity: str = "MEDIUM", description: str = "",
                     mitigation: str = "") -> dict[str, Any]:
    """Raise a risk, assumption, issue or decision.

    Raising is safe in a way that closing is not: an item nobody needed costs
    a line on a register, and an item nobody raised costs the thing it warned
    about. Closing one stays off the conversational path — it is a judgement
    that the risk has gone, and somebody should make it on a screen with their
    name against it.
    """
    row = svc.create_raid(
        session, principal, int(project_id), raid_type=raid_type,
        title=title, description=description, severity=severity,
        mitigation=mitigation, source=SOURCE_AI_CHAT)
    return {"applied": True, "code": row.code, "type": row.raid_type,
            "severity": row.severity, "title": row.title,
            "project_id": int(project_id), "source": SOURCE_AI_CHAT}


def handlers(session: Any) -> dict[str, Any]:
    """Tool id → callable, for the registry's `invoke`.

    Every one takes `principal` because every one is `writes=True`, and that
    is what carries the person into the service's permission check. An agent
    calling these has exactly the access the person asking has.
    """
    from backend.agentic import tools as reg
    from backend.planner.agent import _project_id

    def update(principal=None, project=None, **kw):
        return post_task_update(
            session, principal, _project_id(session, principal, project),
            code=str(kw.get("task") or kw.get("code") or ""),
            percent_complete=(int(kw["percent"])
                              if kw.get("percent") not in (None, "") else None),
            narrative=str(kw.get("narrative") or ""),
            next_step=str(kw.get("next_step") or ""),
            blocked=(bool(kw["blocked"]) if kw.get("blocked") is not None
                     else None),
            blocker_reason=str(kw.get("blocker") or ""))

    def blocker(principal=None, project=None, **kw):
        return set_task_blocker(
            session, principal, _project_id(session, principal, project),
            code=str(kw.get("task") or kw.get("code") or ""),
            reason=str(kw.get("reason") or ""),
            clear=bool(kw.get("clear") or False))

    def raise_item(principal=None, project=None, **kw):
        return create_raid_item(
            session, principal, _project_id(session, principal, project),
            title=str(kw.get("title") or ""),
            raid_type=str(kw.get("type") or "RISK").upper(),
            severity=str(kw.get("severity") or "MEDIUM").upper(),
            description=str(kw.get("description") or ""),
            mitigation=str(kw.get("mitigation") or ""))

    return {
        reg.PLANNER_POST_TASK_UPDATE: update,
        reg.PLANNER_SET_TASK_BLOCKER: blocker,
        reg.PLANNER_CREATE_RAID_ITEM: raise_item,
    }


__all__ = [
    "ACTIONS_VERSION", "CONVERSATIONAL", "NEVER_CONVERSATIONAL", "Refused",
    "post_task_update", "set_task_blocker", "create_raid_item", "handlers",
]
