"""What the agent has actually done on a project, in a person's words.

The project already has two records and neither is this one. `planner_updates`
is what PEOPLE did — a status moved, a percentage changed, somebody wrote a
comment. `planner_reminders` is what the AGENT sent — who was told what, and
whether they came back. A project manager asking "what has the agent been
doing?" wants the second, interleaved with the handful of entries from the
first that are the agent's consequences: the update that answered a chase, and
the health transition the sweep recorded.

Deliberately NOT the scheduler's log. Nobody wants "sweep 4831 evaluated 27
tasks in 380ms" on a project page. The line they want is "Reminder sent to
Sameer — Data Reconciliation due in 3 days", and the one after it is "Sameer
updated it to 40%".

Everything here is read. Nothing in this module writes, and nothing in it
decides: `monitor` decided, this reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    ENTITY_MILESTONE,
    ENTITY_TASK,
    PlannerMilestone,
    PlannerReminder,
    PlannerTask,
    PlannerUpdate,
)
from backend.planner import access as acl
from backend.planner import escalation as esc
from backend.planner.query import people as _people

#: The kinds a reader can filter by. Named for what a person is looking for
#: rather than for the table the row came from.
KIND_REMINDER = "reminder"
KIND_REQUEST = "request"
KIND_ESCALATION = "escalation"
KIND_RESPONSE = "response"
KIND_HEALTH = "health"
KINDS: tuple[str, ...] = (KIND_REMINDER, KIND_REQUEST, KIND_ESCALATION,
                          KIND_RESPONSE, KIND_HEALTH)

#: What each trigger is called on screen. The monitor's trigger names are
#: engine vocabulary; these are the words a project manager uses.
_SAID: dict[str, str] = {
    "due": "Reminder sent",
    "due_today": "Due-today reminder sent",
    "overdue": "Overdue chase sent",
    "stale": "Update requested",
    "blocked": "Blocked task raised",
    "review": "Review reminder sent",
    "milestone": "Milestone reminder sent",
    "milestone_overdue": "Milestone overdue",
    "health": "Project health changed",
    esc.ESCALATED: "Escalated",
    esc.ESCALATED_BLOCKED: "Blocked task escalated",
    esc.MILESTONE_AT_RISK: "Milestone at risk escalated",
    esc.CRITICAL_PATH: "Critical path at risk",
    esc.SPONSOR_ALERT: "Sponsor alerted",
}

_LEVEL_SAID: dict[str, str] = {
    esc.OWN: "to the task's escalation owner",
    esc.MILESTONE: "to the milestone's escalation owner",
    esc.PROJECT: "to the project's escalation contact",
    esc.MANAGER: "to the project manager",
    esc.SPONSOR: "to the sponsor",
}


@dataclass
class Entry:
    """One thing that happened, and everything needed to read it."""

    at: datetime
    kind: str
    headline: str
    detail: str = ""
    person: dict[str, Any] = field(default_factory=dict)
    entity_type: str = ""
    entity_code: str = ""
    entity_id: int | None = None
    level: str = ""
    #: sent | answered | cancelled, for the rows that carry a state.
    state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat() if self.at else "",
            "kind": self.kind, "headline": self.headline,
            "detail": self.detail, "person": self.person,
            "entity_type": self.entity_type, "entity_code": self.entity_code,
            "entity_id": self.entity_id, "level": self.level,
            "state": self.state,
        }


def _codes(session: Any, project_id: int) -> dict[tuple[str, int], str]:
    """Every entity's code, so a reminder can name what it was about.

    Two queries rather than one per reminder: a busy project has hundreds of
    reminders and five milestones.
    """
    found: dict[tuple[str, int], str] = {}
    for row in session.execute(
            select(PlannerTask.id, PlannerTask.code, PlannerTask.title)
            .where(PlannerTask.project_id == int(project_id))):
        found[(ENTITY_TASK, int(row[0]))] = f"{row[1]} — {row[2]}"
    for row in session.execute(
            select(PlannerMilestone.id, PlannerMilestone.code,
                   PlannerMilestone.name)
            .where(PlannerMilestone.project_id == int(project_id))):
        found[(ENTITY_MILESTONE, int(row[0]))] = f"{row[1]} — {row[2]}"
    return found


def _kind_of(row: Any) -> str:
    if str(row.trigger) in esc.TRIGGERS:
        return KIND_ESCALATION
    return KIND_REQUEST if bool(row.asked) else KIND_REMINDER


def agent_activity(session: Any, principal: Any, project_id: int, *,
                   kind: str = "", limit: int = 100,
                   offset: int = 0) -> dict[str, Any]:
    """The agent's own timeline for one project, newest first.

    Read with the caller's permissions. The recipients' names are shown
    because everybody who can see the project can already see who owns what;
    the message BODIES are not, because a reminder is addressed to one person
    and this is a shared page.
    """
    acl.readable(session, int(project_id), principal)
    wanted = str(kind or "").strip().lower()
    if wanted and wanted not in KINDS:
        wanted = ""

    reminders = list(session.execute(
        select(PlannerReminder)
        .where(PlannerReminder.project_id == int(project_id))
        .order_by(PlannerReminder.sent_at.desc())
        .limit(600)).scalars())
    labels = _codes(session, int(project_id))
    directory = _people(session, [r.user_id for r in reminders])

    entries: list[Entry] = []
    for row in reminders:
        said = _SAID.get(str(row.trigger), "Agent action")
        who = directory.get(int(row.user_id), {}) or {}
        name = str(who.get("name") or who.get("username") or "somebody")
        about = labels.get((row.entity_type, int(row.entity_id)), "")
        level = str(row.level or "")
        entries.append(Entry(
            at=row.sent_at, kind=_kind_of(row),
            headline=f"{said} to {name}" if said.endswith("sent")
            else f"{said} — {name}",
            detail=" ".join(part for part in (
                about, str(row.reason or ""),
                _LEVEL_SAID.get(level, "") if level else "") if part).strip(),
            person=who, entity_type=str(row.entity_type),
            entity_code=about.split(" — ")[0] if about else "",
            entity_id=int(row.entity_id), level=level,
            state=str(row.state or "sent")))
        # The answer to a chase is the half a project manager cares about,
        # and it is a fact on the same row rather than a second record.
        if row.responded_at is not None:
            entries.append(Entry(
                at=row.responded_at, kind=KIND_RESPONSE,
                headline=f"{name} responded",
                detail=about, person=who, entity_type=str(row.entity_type),
                entity_code=about.split(" — ")[0] if about else "",
                entity_id=int(row.entity_id), state="answered"))

    for row in session.execute(
            select(PlannerUpdate)
            .where(PlannerUpdate.project_id == int(project_id),
                   PlannerUpdate.action == "health")
            .order_by(PlannerUpdate.created_at.desc()).limit(100)).scalars():
        # The sweep records a colour change with old_status/new_status
        # rather than in `changes`, because a health transition is a status
        # move and the history's status columns are what every other reader
        # of this table already looks at.
        was, now_ = str(row.old_status or ""), str(row.new_status or "")
        if not now_ or was == now_:
            continue
        entries.append(Entry(
            at=row.created_at, kind=KIND_HEALTH,
            headline=f"Project health moved {was or 'UNKNOWN'} \u2192 {now_}",
            detail=str(row.narrative or "")))

    entries.sort(key=lambda e: e.at or datetime.min, reverse=True)
    if wanted:
        entries = [e for e in entries if e.kind == wanted]
    total = len(entries)
    window = entries[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]
    return {"count": total, "kinds": list(KINDS),
            "items": [e.to_dict() for e in window]}


__all__ = ["Entry", "KINDS", "KIND_ESCALATION", "KIND_HEALTH",
           "KIND_REMINDER", "KIND_REQUEST", "KIND_RESPONSE", "agent_activity"]
