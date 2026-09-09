"""Decisions the committee makes, actions that follow, and where the work goes.

The end of the cycle and the beginning of the next one. A committee reads a
pack, decides something, and somebody has to do something about it — and the
thing this module refuses to do is invent a second place for that work to live.

The Planner is the execution source of truth
--------------------------------------------
A committee action LINKS to a `planner_tasks` row. It does not copy the task's
status, its percentage or its due date. Two systems each holding a progress
field is two systems that will eventually disagree, and when they do, the one
on the committee pack is the one that gets read out in a meeting.

So `PlaybookAction` holds the GOVERNANCE record — which committee asked for
this, off which decision, in which pack, and what evidence closed it — and
`progress_of` reads the live state from the Planner every time somebody looks.

What the assistant may and may not do
-------------------------------------
It may draft a decision paper: the question, the recommendation, the
alternatives, the impact. Those are words, and a model writes better ones than
a template does.

It may never record what was decided, and it may never close an action.
`decided_by` and `closed_at` are written only through a path that refuses an
AI-sourced grant, because both are assertions about what happened in a room.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select

from backend.models.playbook import (
    ACTION_STATUSES,
    DECISION_STATUSES,
    PRIORITIES,
    SOURCE_UI,
    PlaybookAction,
    PlaybookDecision,
    PlaybookPack,
)
from backend.playbook import access, readiness, service
from backend.playbook.access import CONTRIBUTOR, EDITOR, PackDenied, PackNotFound
from backend.playbook.service import InvalidPlaybook, record

logger = logging.getLogger(__name__)

#: Decision outcomes only a person may record. Drafting the paper that asks
#: the question is a different operation and an agent may do that.
DECIDED = frozenset({
    "APPROVED", "REJECTED", "CONDITIONALLY_APPROVED", "WITHDRAWN"})

#: Action statuses that mean the work is finished, one way or another.
CLOSED = frozenset({"COMPLETED", "CANCELLED"})

#: How a Planner task's status maps back to a committee action's. Read, never
#: written: this is how the pack reports progress the Planner owns.
FROM_PLANNER: dict[str, str] = {
    "NOT_STARTED": "OPEN",
    "IN_PROGRESS": "IN_PROGRESS",
    "BLOCKED": "BLOCKED",
    "COMPLETE": "COMPLETED",
    "COMPLETED": "COMPLETED",
    "CANCELLED": "CANCELLED",
}


# ------------------------------------------------------------- decisions


def decisions(session: Any, principal: Any, *, committee_id: int | None = None,
              pack_id: int | None = None, status: str | None = None,
              source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """The decision log, by committee or by pack.

    By committee is the useful one. A decision outlives the pack it was raised
    in, and "what has this forum decided" is the question a new member asks
    first.
    """
    if pack_id is not None:
        pack, _ = access.readable_pack(session, pack_id, principal, source)
        query = select(PlaybookDecision).where(
            PlaybookDecision.pack_id == int(pack.id))
    elif committee_id is not None:
        access.committee_grant(session, committee_id, principal, source)
        query = select(PlaybookDecision).where(
            PlaybookDecision.committee_id == int(committee_id))
    else:
        readable = access.readable_committee_ids(session, principal)
        if not readable:
            return []
        query = select(PlaybookDecision).where(
            PlaybookDecision.committee_id.in_(readable))
    if status:
        _one_of(status, DECISION_STATUSES, "decision status")
        query = query.where(PlaybookDecision.status == status.upper())
    rows = session.execute(query.order_by(
        PlaybookDecision.id.desc())).scalars()
    return [_decision_dict(r) for r in rows]


def create_decision(session: Any, pack_id: int, principal: Any, *, title: str,
                    question: str = "", recommendation: str = "",
                    alternatives: list | None = None, impact: str = "",
                    section_id: int | None = None, owner_id: int | None = None,
                    source: str = SOURCE_UI) -> dict[str, Any]:
    """Put a question to the committee.

    Created in DRAFT whoever raises it, including a person. A decision request
    reaches the committee by being written up and moved to REQUIRED, which is
    the moment somebody has decided it is ready to be asked.
    """
    pack, grant = access.writable_pack(
        session, pack_id, principal, CONTRIBUTOR,
        "raise a decision on this pack", source)
    title = _required(title, "a title")
    if not str(question or "").strip():
        raise InvalidPlaybook(
            "A decision request has to say what is being decided. A committee "
            "cannot decide a heading.")
    if section_id is not None:
        section, owner_pack, _ = access.visible_section(
            session, section_id, principal, source)
        if int(owner_pack.id) != int(pack.id):
            raise PackNotFound(f"No section {section_id} in this pack.")

    row = PlaybookDecision(
        committee_id=int(pack.committee_id), pack_id=int(pack.id),
        section_id=section_id,
        reference=_reference(session, pack, PlaybookDecision, "D"),
        title=title.strip()[:240], question=str(question),
        recommendation=str(recommendation or ""),
        alternatives=list(alternatives or []), impact=str(impact or ""),
        status="DRAFT", requested_by=grant.user_id, owner_id=owner_id,
        source=grant.source)
    session.add(row)
    session.flush()
    record(session, entity_type="decision", action="created", pack=pack,
           entity_id=int(row.id), entity_ref=row.reference,
           narrative=f"{row.reference}: {row.title}", grant=grant)
    readiness.refresh(session, pack)
    return _decision_dict(row)


def update_decision(session: Any, decision_id: int, principal: Any, *,
                    source: str = SOURCE_UI, **changes: Any) -> dict[str, Any]:
    """Change a decision paper that has not been decided yet."""
    row, pack, grant = access.visible_decision(
        session, decision_id, principal, source)
    if str(row.status) in DECIDED:
        when = (row.decided_at.date().isoformat() if row.decided_at
                else "a previous date")
        outcome = str(row.status).lower().replace("_", " ")
        raise InvalidPlaybook(
            f"{row.reference} was {outcome} on {when}. What a committee "
            "decided is not edited afterwards; raise a new decision if it "
            "needs revisiting.")
    if pack is not None:
        access.assert_editable(pack)
    if not grant.at_least(CONTRIBUTOR):
        raise PackDenied(
            "Contributor access is needed to write a decision paper.")

    allowed = {"title", "question", "recommendation", "alternatives", "impact",
               "owner_id", "status", "section_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something a decision "
            f"carries at this stage. Changeable: {', '.join(sorted(allowed))}."
            " Recording the outcome is a separate operation.")
    if "status" in changes:
        _one_of(changes["status"], DECISION_STATUSES, "decision status")
        wanted = str(changes["status"]).upper()
        if wanted in DECIDED:
            raise InvalidPlaybook(
                "Recording what the committee decided is a separate "
                "operation, so that the decision carries a name and a date. "
                "Use the decide route.")
        changes["status"] = wanted

    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    moved = service._diff(before, changes)
    if moved:
        session.flush()
        record(session, entity_type="decision", action="updated", pack=pack,
               committee_id=int(row.committee_id), entity_id=int(row.id),
               entity_ref=row.reference, changes=moved, grant=grant)
    return _decision_dict(row)


def decide(session: Any, decision_id: int, principal: Any, *, outcome: str,
           decision_text: str = "", conditions: str = "",
           source: str = SOURCE_UI) -> dict[str, Any]:
    """Record what the committee decided, with a name and a date against it.

    Refused for an AI-sourced grant at any privilege, and refused below
    approver access. This is the record of what happened in a room, and it has
    to be written by somebody who was in it.
    """
    row, pack, grant = access.visible_decision(
        session, decision_id, principal, source)
    access.refuse_ai(grant, "decide")
    if not grant.at_least(access.APPROVER):
        raise PackDenied(
            f"You have {grant.access.lower()} access to this committee. "
            "Recording a committee decision needs approver access.")
    _one_of(outcome, DECISION_STATUSES, "decision outcome")
    wanted = outcome.upper()
    if wanted not in DECIDED:
        raise InvalidPlaybook(
            "Recording an outcome means saying what was decided. One of: "
            f"{', '.join(sorted(DECIDED))}.")
    if str(row.status) in DECIDED:
        raise InvalidPlaybook(
            f"{row.reference} has already been "
            f"{str(row.status).lower().replace('_', ' ')}.")
    if wanted == "CONDITIONALLY_APPROVED" and not str(conditions or "").strip():
        raise InvalidPlaybook(
            "A conditional approval has to say what the conditions are. "
            "Without them nobody can tell whether they have been met.")

    was = str(row.status)
    row.status = wanted
    row.decided_by = grant.user_id
    row.decided_at = datetime.now(UTC)
    row.decision_text = str(decision_text or "")
    row.conditions = str(conditions or "")
    row.updated_at = row.decided_at
    session.flush()
    record(session, entity_type="decision", action="decided", pack=pack,
           committee_id=int(row.committee_id), entity_id=int(row.id),
           entity_ref=row.reference,
           changes={"status": [was, wanted]},
           narrative=decision_text or f"{row.reference} was "
                                      f"{wanted.lower().replace('_', ' ')}.",
           grant=grant)
    return _decision_dict(row)


# --------------------------------------------------------------- actions


def actions(session: Any, principal: Any, *, committee_id: int | None = None,
            pack_id: int | None = None, status: str | None = None,
            mine: bool = False, overdue: bool = False,
            source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """The action log, with live progress read from the Planner."""
    if pack_id is not None:
        pack, _ = access.readable_pack(session, pack_id, principal, source)
        query = select(PlaybookAction).where(
            PlaybookAction.pack_id == int(pack.id))
    elif committee_id is not None:
        access.committee_grant(session, committee_id, principal, source)
        query = select(PlaybookAction).where(
            PlaybookAction.committee_id == int(committee_id))
    else:
        readable = access.readable_committee_ids(session, principal)
        if not readable:
            return []
        query = select(PlaybookAction).where(
            PlaybookAction.committee_id.in_(readable))

    if status:
        _one_of(status, ACTION_STATUSES, "action status")
        query = query.where(PlaybookAction.status == status.upper())
    if mine:
        user_id = getattr(principal, "user_id", None)
        if user_id is None:
            return []
        query = query.where(PlaybookAction.owner_id == int(user_id))
    if overdue:
        query = query.where(
            PlaybookAction.due_date < date.today(),
            PlaybookAction.status.notin_(tuple(CLOSED)))

    rows = session.execute(query.order_by(
        PlaybookAction.due_date.asc().nullslast(),
        PlaybookAction.id.desc())).scalars().all()
    return [_action_dict(session, r) for r in rows]


def create_action(session: Any, pack_id: int, principal: Any, *,
                  description: str, owner_id: int | None = None,
                  due_date: date | None = None, priority: str = "MEDIUM",
                  decision_id: int | None = None, status: str = "DRAFT",
                  source: str = SOURCE_UI) -> dict[str, Any]:
    """Record that somebody agreed to do something.

    An agent may draft one. It lands in DRAFT and stays there until a person
    opens it, because an action nobody has agreed to is a suggestion, and a
    committee action log full of suggestions is one people stop reading.
    """
    pack, grant = access.writable_pack(
        session, pack_id, principal, CONTRIBUTOR,
        "raise an action on this pack", source)
    description = _required(description, "a description of the work")
    _one_of(priority, PRIORITIES, "priority")
    _one_of(status, ACTION_STATUSES, "action status")
    wanted = status.upper()
    if grant.by_ai and wanted != "DRAFT":
        raise PackDenied(
            "An assistant may draft an action. Opening it is a person saying "
            "somebody has agreed to do it.")
    if wanted in CLOSED:
        raise InvalidPlaybook(
            "An action cannot be created already closed. Raise it, then close "
            "it with the evidence.")
    if decision_id is not None:
        decision, _, _ = access.visible_decision(
            session, decision_id, principal, source)
        if int(decision.committee_id) != int(pack.committee_id):
            raise PackNotFound(f"No decision {decision_id}.")

    row = PlaybookAction(
        committee_id=int(pack.committee_id), pack_id=int(pack.id),
        decision_id=decision_id,
        reference=_reference(session, pack, PlaybookAction, "A"),
        description=str(description), owner_id=owner_id, due_date=due_date,
        priority=priority.upper(), status=wanted, source=grant.source,
        created_by=grant.user_id)
    session.add(row)
    session.flush()
    record(session, entity_type="action", action="created", pack=pack,
           entity_id=int(row.id), entity_ref=row.reference,
           narrative=f"{row.reference}: {row.description[:120]}", grant=grant)
    readiness.refresh(session, pack)
    return _action_dict(session, row)


def update_action(session: Any, action_id: int, principal: Any, *,
                  source: str = SOURCE_UI, **changes: Any) -> dict[str, Any]:
    """Change an action, or post an update against it.

    `latest_update` is the field a committee actually reads: an action with no
    update since it was raised is one the pack cannot say anything about, and
    the readiness check says so.
    """
    row, pack, grant = access.visible_action(
        session, action_id, principal, source)
    allowed = {"description", "owner_id", "due_date", "priority", "status",
               "latest_update", "closure_evidence"}
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidPlaybook(
            f"{', '.join(sorted(unknown))} is not something an action "
            f"carries. Changeable: {', '.join(sorted(allowed))}.")

    mine = (grant.user_id is not None and row.owner_id == grant.user_id)
    if not mine and not grant.at_least(EDITOR):
        raise PackDenied(
            f"{row.reference} belongs to somebody else. An action is updated "
            "by its owner, or by somebody with editor access to the "
            "committee.")

    if "status" in changes:
        _one_of(changes["status"], ACTION_STATUSES, "action status")
        wanted = str(changes["status"]).upper()
        if wanted in CLOSED:
            raise InvalidPlaybook(
                "Closing an action asserts the work was done, so it is a "
                "separate operation that records the evidence and the date. "
                "Use the close route.")
        changes["status"] = wanted
    if grant.by_ai:
        # An agent may post an update it has observed — a linked task moved,
        # a due date passed. It may not reassign the work or move the date.
        moving = set(changes) - {"latest_update"}
        if moving:
            raise PackDenied(
                "An assistant may post an update on an action. Changing who "
                f"owns it or when it is due is a person's decision "
                f"({', '.join(sorted(moving))}).")

    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    moved = service._diff(before, changes)
    if moved:
        session.flush()
        record(session, entity_type="action", action="updated", pack=pack,
               committee_id=int(row.committee_id), entity_id=int(row.id),
               entity_ref=row.reference, changes=moved,
               narrative=str(changes.get("latest_update") or ""), grant=grant)
        if pack is not None:
            readiness.refresh(session, pack)
    return _action_dict(session, row)


def close_action(session: Any, action_id: int, principal: Any, *,
                 evidence: str, completed: bool = True,
                 source: str = SOURCE_UI) -> dict[str, Any]:
    """Say the work is done, and say what shows it.

    Refused for an AI-sourced grant. Closing an action asserts the work
    happened, and the person who did it asserts that.
    """
    row, pack, grant = access.visible_action(
        session, action_id, principal, source)
    access.refuse_ai(grant, "close_action")
    mine = (grant.user_id is not None and row.owner_id == grant.user_id)
    if not mine and not grant.at_least(EDITOR):
        raise PackDenied(
            f"{row.reference} is somebody else's to close. An action is closed "
            "by its owner, or by somebody with editor access to the "
            "committee.")
    if str(row.status) in CLOSED:
        raise InvalidPlaybook(
            f"{row.reference} is already "
            f"{str(row.status).lower()}.")
    if completed and not str(evidence or "").strip():
        raise InvalidPlaybook(
            "Closing an action needs a sentence saying what shows the work "
            "was done. A committee reading a closed action with no evidence "
            "has to take it on trust, which is the thing an action log exists "
            "to avoid.")

    was = str(row.status)
    row.status = "COMPLETED" if completed else "CANCELLED"
    row.closure_evidence = str(evidence or "")
    row.closed_at = datetime.now(UTC)
    row.updated_at = row.closed_at
    session.flush()
    record(session, entity_type="action", action="closed", pack=pack,
           committee_id=int(row.committee_id), entity_id=int(row.id),
           entity_ref=row.reference, changes={"status": [was, row.status]},
           narrative=evidence, grant=grant)
    return _action_dict(session, row)


# ------------------------------------------------------ the Planner bridge


def link_to_planner(session: Any, action_id: int, principal: Any, *,
                    project_id: int, task_code: str = "",
                    workstream_id: int | None = None,
                    source: str = SOURCE_UI) -> dict[str, Any]:
    """Turn a committee action into real work, in the Planner.

    Creates a Planner task through the Planner's OWN service, so its access
    rules, its code validation and its own event record all apply. Playbook
    does not reach into `planner_tasks` and never will: two writers on one
    table is two sets of rules, and the second one is always the one that is
    wrong.
    """
    from backend.planner import access as planner_access
    from backend.planner import service as planner

    row, pack, grant = access.visible_action(
        session, action_id, principal, source)
    if not grant.at_least(CONTRIBUTOR):
        raise PackDenied(
            "Contributor access is needed to send a committee action to the "
            "Planner.")
    if row.planner_task_id is not None:
        raise InvalidPlaybook(
            f"{row.reference} is already linked to a Planner task. Unlink it "
            "first if it belongs somewhere else.")

    # The Planner decides whether this caller may add a task to that project.
    # Its refusal is the right one and is passed through unchanged rather than
    # being re-worded here, where it would go stale.
    try:
        task = planner.create_task(
            session, principal, int(project_id),
            code=(task_code or row.reference or f"CA-{row.id}")[:32],
            title=str(row.description)[:200],
            description=_planner_description(session, row, pack),
            owner_id=row.owner_id, workstream_id=workstream_id,
            due_date=row.due_date, priority=str(row.priority),
            source=grant.source)
    except planner_access.ProjectNotFound as e:
        raise PackNotFound(str(e)) from e

    row.planner_project_id = int(project_id)
    row.planner_task_id = int(task.id)
    row.linked_at = datetime.now(UTC)
    row.linked_by = grant.user_id
    if str(row.status) == "DRAFT":
        row.status = "OPEN"
    session.flush()
    record(session, entity_type="action", action="linked", pack=pack,
           committee_id=int(row.committee_id), entity_id=int(row.id),
           entity_ref=row.reference,
           changes={"planner_task_id": [None, int(task.id)]},
           narrative=(f"Sent to the Project Planner as {task.code}. Progress "
                      "is read from there from now on."),
           grant=grant)
    return _action_dict(session, row)


def _planner_description(session: Any, row: Any, pack: Any) -> str:
    """Why this task exists, written into the Planner task itself.

    Somebody opening a task in the Planner three weeks later should be able to
    see which committee asked for it without following a link back.
    """
    from backend.models.playbook import PlaybookCommittee

    committee = session.get(PlaybookCommittee, int(row.committee_id))
    bits = [str(row.description)]
    where = committee.name if committee is not None else "a committee"
    if pack is not None:
        bits.append(f"\nRaised by {where} in {pack.code} ({pack.name}).")
    else:
        bits.append(f"\nRaised by {where}.")
    if row.decision_id is not None:
        decision = session.get(PlaybookDecision, int(row.decision_id))
        if decision is not None:
            bits.append(f"Follows decision {decision.reference}: "
                        f"{decision.title}")
    return "\n".join(bits)


def progress_of(session: Any, row: Any) -> dict[str, Any]:
    """Live state from the Planner, read and never copied.

    Returns `linked: False` rather than guessing when there is no task. An
    action somebody is tracking outside CreditProbe has no percentage here,
    and inventing one would be worse than the blank.
    """
    if row.planner_task_id is None:
        if row.linked_at is not None:
            # It WAS linked. The foreign key is ON DELETE SET NULL, so a task
            # deleted in the Planner empties the column — and an action that
            # silently reverted to "not linked" would tell a committee the
            # work was never sent anywhere. `linked_at` survives the delete,
            # which is what makes the difference detectable at all.
            return {
                "linked": False, "was_linked": True,
                "linked_at": row.linked_at.isoformat(),
                "note": ("The Planner task this action was sent to has been "
                         "deleted, so there is no live progress to read. The "
                         "action itself is unaffected and can be linked "
                         "again."),
            }
        return {"linked": False}
    from backend.models.planner import PlannerTask

    task = session.get(PlannerTask, int(row.planner_task_id))
    if task is None:
        # Reachable only inside a transaction where the task row has gone but
        # the foreign key has not yet been nulled. Same fact, said the same
        # way.
        return {"linked": False, "was_linked": True,
                "note": "The Planner task this action was sent to no longer "
                        "exists."}
    return {
        "linked": True, "task_found": True,
        "task_id": int(task.id), "task_code": str(task.code),
        "project_id": int(task.project_id),
        "planner_status": str(task.status),
        "status": FROM_PLANNER.get(str(task.status), "IN_PROGRESS"),
        "percent_complete": float(task.percent_complete or 0),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "blocked": bool(task.blocked),
        "blocker_reason": str(task.blocker_reason or ""),
        "next_step": str(task.next_step or ""),
    }


# ---------------------------------------------------------------- helpers


def carry_forward(session: Any, pack_id: int, principal: Any, *,
                  source: str = SOURCE_UI) -> list[dict[str, Any]]:
    """Every open action this committee is carrying, for the next pack.

    Not copied into the new pack. The action belongs to the committee and
    keeps its identity across meetings; copying it would produce a second row
    with the same reference and two places to update it.
    """
    pack, _ = access.readable_pack(session, pack_id, principal, source)
    rows = session.execute(
        select(PlaybookAction).where(
            PlaybookAction.committee_id == pack.committee_id,
            PlaybookAction.status.notin_(tuple(CLOSED) + ("DRAFT",)))
        .order_by(PlaybookAction.due_date.asc().nullslast())).scalars().all()
    return [_action_dict(session, r) for r in rows]


def _reference(session: Any, pack: Any, model: Any, prefix: str) -> str:
    """A short human reference — RCRC-2026-03-D1 — unique within the pack.

    Read out in meetings and written in minutes, which is why it is not an id.
    """
    used = int(session.execute(
        select(func.count()).select_from(model)
        .where(model.pack_id == pack.id)).scalar_one() or 0)
    return f"{pack.code}-{prefix}{used + 1}"[:40]


def _required(value: str, what: str) -> str:
    if not str(value or "").strip():
        raise InvalidPlaybook(f"This needs {what}.")
    return str(value)


def _one_of(value: Any, allowed: Any, what: str) -> None:
    if str(value or "").upper() not in allowed:
        raise InvalidPlaybook(
            f"'{value}' is not a {what} this product records. One of: "
            f"{', '.join(sorted(allowed))}.")


def _decision_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row.id), "committee_id": int(row.committee_id),
        "pack_id": row.pack_id, "section_id": row.section_id,
        "reference": str(row.reference), "title": str(row.title),
        "question": str(row.question),
        "recommendation": str(row.recommendation),
        "alternatives": list(row.alternatives or []),
        "impact": str(row.impact), "status": str(row.status),
        "status_label": str(row.status).replace("_", " ").title(),
        "decided": str(row.status) in DECIDED,
        "requested_by": row.requested_by, "owner_id": row.owner_id,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_text": str(row.decision_text),
        "conditions": str(row.conditions), "source": str(row.source),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _action_dict(session: Any, row: Any) -> dict[str, Any]:
    progress = progress_of(session, row)
    return {
        "id": int(row.id), "committee_id": int(row.committee_id),
        "pack_id": row.pack_id, "decision_id": row.decision_id,
        "reference": str(row.reference), "description": str(row.description),
        "owner_id": row.owner_id,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "priority": str(row.priority), "status": str(row.status),
        "status_label": str(row.status).replace("_", " ").title(),
        "latest_update": str(row.latest_update),
        "closure_evidence": str(row.closure_evidence),
        "closed": str(row.status) in CLOSED,
        "overdue": bool(row.due_date and row.due_date < date.today()
                        and str(row.status) not in CLOSED),
        "planner": progress,
        "planner_project_id": row.planner_project_id,
        "planner_task_id": row.planner_task_id,
        "linked_at": row.linked_at.isoformat() if row.linked_at else None,
        "source": str(row.source),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


def pack_of(session: Any, row: Any) -> Any:
    return (session.get(PlaybookPack, int(row.pack_id))
            if row.pack_id is not None else None)


__all__ = [
    "CLOSED", "DECIDED", "FROM_PLANNER", "actions", "carry_forward",
    "close_action", "create_action", "create_decision", "decide", "decisions",
    "link_to_planner", "pack_of", "progress_of", "update_action",
    "update_decision",
]
