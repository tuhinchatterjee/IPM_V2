"""Rolling a seeded demonstration forward, without rebuilding it.

The seed writes every date as an offset from the day it ran — a sign-off due
"in three days". That is true on the day and decays afterwards: the next
morning it is due in two, two is not one of the project's reminder thresholds,
and the demonstration's centrepiece stops being able to fire on its own. The
regression that caught it went green before UTC midnight and red after, with
nothing in the tree changed between the two runs.

The obvious repair — re-seed — is the wrong one. `--reset` deletes and rebuilds
the four programmes, and by the time somebody has been demonstrating with them
for a week those rows carry their own edits, their own updates and their own
history. Losing a person's work to fix a date is a worse outcome than the date.

So this re-anchors instead. Every demo project stores the day its dates were
relative to; the shift is `today - anchor`; every canonical scheduling field
moves by that many days and the anchor becomes today. Run twice on one day the
shift is zero and nothing is written, which is what makes it idempotent.

What it will not touch
----------------------
Progress, status, owner, reviewer, contributors, participants and their roles,
narrative updates, RAID text and state, blockers, next steps, notes, tags,
history and audit. Only the scheduling fields listed in `FIELDS` move, and only
on projects whose `demo_origin` says CreditProbe seeded them. A project a
person created has an empty `demo_origin` and is never a candidate, which is
why the marker is a stored column rather than a guess from the project code.

Where a person has moved a date themselves
------------------------------------------
That date is a commitment somebody made, not scaffolding. The planner's history
is append-only and records `{field: [before, after]}` with the source that made
each change, so a human date edit is findable: a `PlannerUpdate` on that entity,
touching that field, from a source that is not SYSTEM. Those fields are **held**
— reported, and left exactly as the person set them — unless the caller passes
`force=True`, which is the only way to overwrite a human commitment and says so
in the report and in the history it writes.

Why not `service.update_task`
-----------------------------
Because it answers chases. Every task update calls `_close_requests`, which
marks any outstanding update request as answered by the person who saved. A
date re-anchor is not an answer to "you owe us an update on this", and silently
closing somebody's chase would corrupt exactly the workflow the demonstration
exists to show. The moves are applied to the rows and then written through the
service layer's own `record`, `audit` and `signal` — the same history table,
the same audit trail, the same re-evaluation signal — with the source set to
SYSTEM so nobody appears to have made a change they did not make.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.models.planner import (
    ENTITY_MILESTONE,
    ENTITY_PROJECT,
    ENTITY_RAID,
    ENTITY_TASK,
    SOURCE_SYSTEM,
    PlannerMilestone,
    PlannerProject,
    PlannerRaid,
    PlannerTask,
    PlannerUpdate,
)
from backend.planner import service as svc

logger = logging.getLogger(__name__)

#: What `demo_origin` says on programmes this repository's seed built.
RETAIL_DEMO = "creditprobe.retail_demo"

#: The canonical scheduling fields, per entity, and the ONLY fields this moves.
#: Anything not on this list is a person's content and is left alone.
FIELDS: dict[str, tuple[str, ...]] = {
    ENTITY_PROJECT: ("start_date", "target_end_date", "actual_end_date"),
    ENTITY_TASK: ("start_date", "due_date", "completed_date"),
    ENTITY_MILESTONE: ("target_date", "actual_date"),
    ENTITY_RAID: ("raised_date", "target_date", "resolved_date"),
}

_MODELS = {
    ENTITY_PROJECT: PlannerProject,
    ENTITY_TASK: PlannerTask,
    ENTITY_MILESTONE: PlannerMilestone,
    ENTITY_RAID: PlannerRaid,
}

#: Every date field name any entity has, for reading the history back.
_ALL_DATE_FIELDS = {name for names in FIELDS.values() for name in names}


class NotADemoProject(ValueError):
    """Asked to refresh something CreditProbe did not seed."""


@dataclass
class Move:
    """One date that would move, or one that is being held back."""

    entity_type: str
    entity_id: int
    entity_code: str
    field: str
    before: date | None
    after: date | None
    #: True when a person set this date themselves and it is being preserved.
    held: bool = False
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"entity_type": self.entity_type, "entity_id": self.entity_id,
                "entity_code": self.entity_code, "field": self.field,
                "before": str(self.before or ""), "after": str(self.after or ""),
                "held": self.held, "why": self.why}


@dataclass
class ProjectPlan:
    """What one demo programme would have done to it."""

    project_id: int
    code: str
    name: str
    anchor: date | None
    shift_days: int
    moves: list[Move] = field(default_factory=list)

    @property
    def held(self) -> list[Move]:
        return [m for m in self.moves if m.held]

    @property
    def moving(self) -> list[Move]:
        return [m for m in self.moves if not m.held]

    def to_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "code": self.code,
                "name": self.name, "anchor": str(self.anchor or ""),
                "shift_days": self.shift_days,
                "moves": [m.to_dict() for m in self.moving],
                "held": [m.to_dict() for m in self.held]}


@dataclass
class Refresh:
    """Everything the refresh would do, or did."""

    today: date
    projects: list[ProjectPlan] = field(default_factory=list)
    applied: bool = False
    forced: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def moves(self) -> int:
        return sum(len(p.moving) for p in self.projects)

    @property
    def held(self) -> int:
        return sum(len(p.held) for p in self.projects)

    def to_dict(self) -> dict[str, Any]:
        return {"today": str(self.today), "applied": self.applied,
                "forced": self.forced, "moved": self.moves, "held": self.held,
                "projects": [p.to_dict() for p in self.projects],
                "notes": self.notes}


# --------------------------------------------------------------- finding them


def demo_projects(session: Any, *, origin: str = "") -> list[PlannerProject]:
    """Programmes CreditProbe seeded. Never one a person created.

    Ordered by code so a dry run reads the same way twice.
    """
    from sqlalchemy import select

    query = select(PlannerProject).where(PlannerProject.demo_origin != "")
    if origin:
        query = query.where(PlannerProject.demo_origin == origin)
    return list(session.execute(query.order_by(PlannerProject.code))
                .scalars().all())


def human_edited(session: Any, project_id: int) -> set[tuple[str, int, str]]:
    """Which (entity_type, entity_id, field) a person moved themselves.

    Read from the append-only history rather than inferred from the row: the
    row only knows what a date is now, and "somebody chose this" and "the seed
    wrote this" look identical there. `PlannerUpdate.changes` is
    `{field: [before, after]}` and `source` says what made the change, so a
    human date edit is exactly a row touching a date field from a source that
    is not SYSTEM.
    """
    from sqlalchemy import select

    rows = session.execute(
        select(PlannerUpdate.entity_type, PlannerUpdate.entity_id,
               PlannerUpdate.changes)
        .where(PlannerUpdate.project_id == int(project_id),
               PlannerUpdate.source != SOURCE_SYSTEM)).all()
    found: set[tuple[str, int, str]] = set()
    for entity_type, entity_id, changes in rows:
        if entity_id is None or not isinstance(changes, dict):
            continue
        for name in changes:
            if name in _ALL_DATE_FIELDS:
                found.add((str(entity_type), int(entity_id), str(name)))
    return found


# ------------------------------------------------------------------ planning


def _rows(session: Any, project: PlannerProject
          ) -> list[tuple[str, Any, str]]:
    """Every entity whose dates are in scope, with its human-facing code."""
    from sqlalchemy import select

    out: list[tuple[str, Any, str]] = [(ENTITY_PROJECT, project, project.code)]
    for kind in (ENTITY_TASK, ENTITY_MILESTONE, ENTITY_RAID):
        model = _MODELS[kind]
        rows = session.execute(
            select(model).where(model.project_id == int(project.id))
            .order_by(model.id)).scalars().all()
        out.extend((kind, row, str(getattr(row, "code", "") or "")) for row in rows)
    return out


def plan(session: Any, *, today: date | None = None, force: bool = False,
         origin: str = "", project_ids: list[int] | None = None) -> Refresh:
    """What a refresh would change, without changing anything.

    This is what `--dry-run` prints and what `apply` then executes, so the two
    cannot disagree: there is one calculation and the second call is the only
    one that writes.
    """
    when = today or date.today()
    out = Refresh(today=when, forced=force)

    for project in demo_projects(session, origin=origin):
        if project_ids is not None and int(project.id) not in project_ids:
            continue
        anchor = project.demo_anchor_date
        if anchor is None:
            out.notes.append(
                f"{project.code} is marked as a demo programme but has no "
                "anchor date, so there is no way to know how far its dates "
                "have drifted. Left alone.")
            continue

        shift = (when - anchor).days
        entry = ProjectPlan(int(project.id), project.code, project.name,
                            anchor, shift)
        out.projects.append(entry)
        if shift == 0:
            continue
        if shift < 0 and not force:
            # An anchor in the future means the anchor is wrong, not that the
            # demonstration belongs in the past. "Refresh to today" that moves
            # work backwards would look like a working command and quietly
            # undo a day of it, so it stops and says what it found.
            out.notes.append(
                f"{project.code} is anchored to {anchor}, which is after "
                f"{when}. Refusing to move its dates backwards — check the "
                "anchor before forcing this.")
            entry.moves.clear()
            continue

        overrides = set() if force else human_edited(session, int(project.id))
        for kind, row, code in _rows(session, project):
            for name in FIELDS[kind]:
                before = getattr(row, name, None)
                if before is None:
                    continue
                key = (kind, int(row.id), name)
                if key in overrides:
                    entry.moves.append(Move(
                        kind, int(row.id), code, name, before, before,
                        held=True,
                        why="A person set this date after the demonstration "
                            "was seeded. It is a commitment, not scaffolding."))
                    continue
                entry.moves.append(Move(kind, int(row.id), code, name, before,
                                        before + timedelta(days=shift)))
    return out


# ----------------------------------------------------------------- applying


def apply(session: Any, *, today: date | None = None, force: bool = False,
          origin: str = "", project_ids: list[int] | None = None) -> Refresh:
    """Re-anchor the demo programmes, and say exactly what moved.

    Idempotent for one calendar date: the shift is computed from the stored
    anchor, so a second run on the same day computes zero and writes nothing —
    not even a history row, because "nothing changed" is not an event.

    Nobody is passed as the actor and none is needed: what this may touch is
    decided by `demo_origin`, not by who is asking, and the marker is on four
    rows CreditProbe wrote. The caller is the guarded CLI; there is deliberately
    no HTTP route, because a demonstration-maintenance operation reachable over
    the API is one an unauthenticated request will eventually find.
    """
    out = plan(session, today=today, force=force, origin=origin,
               project_ids=project_ids)
    when = out.today

    for entry in out.projects:
        if entry.shift_days == 0 or not entry.moving:
            continue
        project = session.get(PlannerProject, entry.project_id)
        if project is None:  # pragma: no cover - deleted between plan and apply
            continue

        by_entity: dict[tuple[str, int], list[Move]] = {}
        for move in entry.moving:
            by_entity.setdefault((move.entity_type, move.entity_id),
                                 []).append(move)

        for (kind, entity_id), moves in by_entity.items():
            row = (project if kind == ENTITY_PROJECT
                   else session.get(_MODELS[kind], entity_id))
            if row is None:  # pragma: no cover - deleted between plan and apply
                continue
            changes: dict[str, Any] = {}
            for move in moves:
                setattr(row, move.field, move.after)
                changes[move.field] = [str(move.before), str(move.after)]
            svc._bump(row, None)
            svc.record(
                session, entry.project_id, entity_type=kind,
                entity_id=int(entity_id), entity_code=moves[0].entity_code,
                action="date", author_id=None, source=SOURCE_SYSTEM,
                narrative=(
                    f"Demonstration dates re-anchored from {entry.anchor} to "
                    f"{when} ({entry.shift_days:+d} days)."
                    + (" Human-set dates were overwritten because the refresh "
                       "was forced." if force else "")),
                changes=changes)

        project.demo_anchor_date = when
        svc.audit(session, "PLANNER_DEMO_DATES_REFRESHED", actor_id=None,
                  project_id=entry.project_id, source=SOURCE_SYSTEM,
                  code=entry.code, anchor_was=str(entry.anchor),
                  anchor_now=str(when), shift_days=entry.shift_days,
                  moved=len(entry.moving), held=len(entry.held),
                  forced=bool(force))
        # Re-evaluate: the reminder fingerprint carries the due date, so a
        # moved date is a new commitment and re-arms its own reminder. The
        # signal is what makes that happen now rather than on the next sweep.
        svc.signal(session, entry.project_id, "task_due_date_changed")

    out.applied = True
    return out


__all__ = ["RETAIL_DEMO", "FIELDS", "Move", "ProjectPlan", "Refresh",
           "NotADemoProject", "demo_projects", "human_edited", "plan", "apply"]
