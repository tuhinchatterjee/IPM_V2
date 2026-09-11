"""A project before it is a project.

The Copilot gathers a plan in conversation and in panels, and neither of those
is a project until somebody says publish. This module is the thing in between:
the document that is being built, the rules about when it is complete enough
to become real, and the single atomic transaction that turns it into ordinary
planner rows.

Three commitments shape it.

**One draft, two ways in.** Chat and the structured panel write the same
document through the same functions. There is no chat draft and no panel
draft, so a person who types three milestones and then edits the fourth in the
table is editing one plan. `apply` is the only writer.

**Publish goes through the ordinary service layer.** Every row this module
creates is created by `service.create_project`, `create_milestone`,
`create_task`, `create_dependency` — the same functions the UI calls, with the
same permission checks, the same audit, the same cycle detection and the same
event signalling. A publish path that wrote rows directly would be a second
implementation of the planner with none of its governance, and the first time
they disagreed the disagreement would be silent.

**Atomic or nothing.** A publish that fails halfway must leave no project. The
whole publication runs inside one transaction and the caller commits; any
exception rolls the lot back. A half-created project is worse than no project,
because somebody would find it and work on it.

The document
------------
    {
      "version": "1.0.0",
      "overview": {"name", "code", "description", "objective"},
      "governance": {"sponsor_id", "manager_id", "owner_id", "escalation_id",
                     "priority", "status", "start_date", "target_end_date",
                     "reporting_cadence"},
      "agentic": {"mode", "policy": {...}},
      "milestones": [{"code", "name", ...}],
      "tasks": [{"code", "milestone_code", "title", ...}],
      "links": [{"predecessor", "successor", "dependency_type", "lag_days"}],
    }

Codes are generated once and never regenerated: `M01`, `M01-T01`. They are how
a person refers to a row in chat, in an export and in a status report, and a
code that changed on publish would break every one of those.
"""

from __future__ import annotations

import copy
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.models.planner import (
    ACCESS_CONTRIBUTOR,
    ACCESS_EDITOR,
    ACCESS_VIEWER,
    CADENCE_WEEKLY,
    CADENCES,
    DEP_FINISH_TO_START,
    DEPENDENCY_TYPES,
    DRAFT_DRAFTING,
    DRAFT_PUBLISHED,
    DRAFT_STATUSES,
    DRAFT_STEPS,
    ENTITY_MILESTONE,
    ENTITY_TASK,
    MILESTONE_STATUSES,
    PRIORITIES,
    PRIORITY_MEDIUM,
    PROJECT_STATUSES,
    ROLE_CONTRIBUTOR,
    ROLE_MANAGER,
    ROLE_OWNER,
    ROLE_REVIEWER,
    ROLE_SPONSOR,
    ROLE_VIEWER,
    ROLE_WORKSTREAM_LEAD,
    SOURCE_UI,
    STEP_AGENTIC,
    STEP_DEPENDENCIES,
    STEP_GOVERNANCE,
    STEP_MILESTONES,
    STEP_OVERVIEW,
    STEP_REVIEW,
    STEP_TASKS,
    TASK_STATUSES,
    PlannerDraft,
    PlannerProject,
)
from backend.planner import access as acl
from backend.planner import control, schedule, service
from backend.planner import policy as policy_mod

DRAFT_VERSION = "1.0.0"

#: A completeness item that must be resolved before publish.
BLOCKER = "BLOCKER"
#: Something a careful person would fix, that does not prevent publishing. A
#: task with no dependency is a valid task, and a plan where every gap is a
#: blocker is a plan nobody finishes drafting.
WARNING = "WARNING"


class DraftError(ValueError):
    """The draft cannot do what was asked of it."""


# ------------------------------------------------------------------ shapes


@dataclass
class Note:
    """One completeness finding.

    `field` is what makes it clickable. A note that says the project has no
    sponsor and cannot say WHERE the sponsor is set leaves the reader to find
    it, and on a form of eight steps that is a search. It is an address in the
    plan — `governance.sponsor_id`, `milestone.M01.owner_id` — which the form
    turns into the element to scroll to and focus. Empty when the finding is
    about the plan rather than about a field, such as a loop in the
    dependencies.
    """

    level: str
    scope: str
    code: str
    message: str
    fix: str = ""
    field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "scope": self.scope, "code": self.code,
                "message": self.message, "fix": self.fix, "field": self.field}


@dataclass
class Completeness:
    """What a draft still needs, separated by whether it stops publication."""

    notes: list[Note] = field(default_factory=list)

    @property
    def blockers(self) -> list[Note]:
        return [n for n in self.notes if n.level == BLOCKER]

    @property
    def warnings(self) -> list[Note]:
        return [n for n in self.notes if n.level == WARNING]

    @property
    def publishable(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "publishable": self.publishable,
            "blockers": [n.to_dict() for n in self.blockers],
            "warnings": [n.to_dict() for n in self.warnings],
            "complete": not self.notes,
        }


# ------------------------------------------------------------- the document


def empty() -> dict[str, Any]:
    """A new plan, with the defaults a person would otherwise have to type."""
    return {
        "version": DRAFT_VERSION,
        "overview": {"name": "", "code": "", "description": "",
                     "objective": ""},
        "governance": {
            "sponsor_id": None, "manager_id": None, "owner_id": None,
            "escalation_id": None, "priority": PRIORITY_MEDIUM,
            "status": "ACTIVE", "start_date": None, "target_end_date": None,
            "reporting_cadence": CADENCE_WEEKLY},
        "agentic": {"mode": policy_mod.MODE_STANDARD, "policy": {}},
        "milestones": [],
        "tasks": [],
        "links": [],
    }


_CODE_SAFE = re.compile(r"[^A-Za-z0-9]+")


def suggest_code(name: str, *, today: date | None = None) -> str:
    """A readable project code from the project's name.

    `LGD Model Redevelopment` becomes `LGD-2026`. Initials rather than the
    whole name because the code is typed, said out loud and put in a
    spreadsheet column, and because a person can override it.
    """
    words = [w for w in _CODE_SAFE.sub(" ", str(name or "")).split() if w]
    skip = {"the", "a", "an", "of", "for", "and", "to", "project", "new"}
    letters = "".join(w[0] for w in words if w.lower() not in skip)[:6].upper()
    if not letters:
        letters = "PROJ"
    year = (today or date.today()).year
    return f"{letters}-{year}"


def milestone_code(index: int) -> str:
    """`M01`. Two digits, because a plan with a hundred milestones is not one."""
    return f"M{index:02d}"


def task_code(milestone: str, index: int) -> str:
    """`M01-T01`, so a task says which milestone it belongs to when quoted."""
    return f"{milestone}-T{index:02d}"


# ----------------------------------------------------------------- reading


def _as_date(value: Any, what: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise DraftError(
            f"{what} is not a date I can read. Use a form like 2026-10-01, or "
            "tell me the date in words and I will interpret it.") from exc


def _one_of(value: Any, allowed: tuple[str, ...], what: str,
            fallback: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return fallback
    if text not in allowed:
        raise DraftError(f"{what} must be one of {', '.join(allowed)}.")
    return text


def milestones_of(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(plan.get("milestones") or [])


def tasks_of(plan: dict[str, Any], milestone_code_: str = "") -> \
        list[dict[str, Any]]:
    rows = list(plan.get("tasks") or [])
    if not milestone_code_:
        return rows
    return [t for t in rows if t.get("milestone_code") == milestone_code_]


def links_of(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return list(plan.get("links") or [])


def item(plan: dict[str, Any], code: str) -> dict[str, Any] | None:
    """One milestone or task by its code. Codes are unique across both."""
    wanted = str(code or "").strip().upper()
    if not wanted:
        return None
    for row in milestones_of(plan):
        if str(row.get("code", "")).upper() == wanted:
            return row
    for row in tasks_of(plan):
        if str(row.get("code", "")).upper() == wanted:
            return row
    return None


def kind_of(plan: dict[str, Any], code: str) -> str:
    """Whether a code names a milestone or a task, for the dependency rows."""
    wanted = str(code or "").strip().upper()
    if any(str(m.get("code", "")).upper() == wanted
           for m in milestones_of(plan)):
        return ENTITY_MILESTONE
    return ENTITY_TASK


def catalogue(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything a dependency could point at, for the Link catalogue.

    Milestones first, then tasks in milestone order, because that is the order
    a person holds the plan in their head.
    """
    found: list[dict[str, Any]] = []
    for milestone in milestones_of(plan):
        found.append({
            "code": milestone.get("code", ""), "kind": ENTITY_MILESTONE,
            "name": milestone.get("name", ""),
            "milestone": milestone.get("code", ""),
            "owner_id": milestone.get("owner_id"),
            "start_date": milestone.get("start_date"),
            "end_date": milestone.get("target_date")})
        for task in tasks_of(plan, str(milestone.get("code", ""))):
            found.append({
                "code": task.get("code", ""), "kind": ENTITY_TASK,
                "name": task.get("title", ""),
                "milestone": milestone.get("code", ""),
                "owner_id": task.get("owner_id"),
                "start_date": task.get("start_date"),
                "end_date": task.get("due_date")})
    return found


# -------------------------------------------------------- escalation ladder


def escalation_for(plan: dict[str, Any], code: str) -> dict[str, Any]:
    """Who a delay on this item reaches, and where that was decided.

    The ladder is task → milestone → project. Returned with its source so the
    screen can say "inherited from Data Foundation" rather than repeating a
    name the person never typed there.
    """
    row = item(plan, code)
    if row is None:
        return {"user_id": None, "source": "", "from_code": ""}
    own = row.get("escalation_id")
    if own:
        return {"user_id": int(own), "source": "own", "from_code": code}

    if row.get("milestone_code"):
        parent = item(plan, str(row["milestone_code"]))
        if parent and parent.get("escalation_id"):
            return {"user_id": int(parent["escalation_id"]),
                    "source": "milestone",
                    "from_code": str(parent.get("code", ""))}

    project = (plan.get("governance") or {}).get("escalation_id")
    if project:
        return {"user_id": int(project), "source": "project", "from_code": ""}
    return {"user_id": None, "source": "", "from_code": ""}


# ----------------------------------------------------------- dependencies


def _dep_key(link: dict[str, Any]) -> tuple[str, str]:
    return (str(link.get("predecessor", "")).upper(),
            str(link.get("successor", "")).upper())


def _synthetic(plan: dict[str, Any]) -> dict[str, int]:
    """Draft codes have no ids, and `control.cycle` needs some.

    Numbered off the catalogue so the mapping is stable within one call, which
    is all the cycle check needs. Reusing the engine rather than writing a
    second graph walk: a draft that publishes a cycle the real engine would
    have rejected is exactly the bug this avoids.
    """
    return {str(row["code"]).upper(): index + 1
            for index, row in enumerate(catalogue(plan))}


def link_preview(plan: dict[str, Any], predecessor: str, successor: str, *,
                 dependency_type: str = DEP_FINISH_TO_START,
                 lag_days: int = 0) -> dict[str, Any]:
    """What this link would do, before it does it.

    Never applies anything. The caller shows this, the person decides, and a
    second call applies it — because a dependency that silently moved a date
    somebody had committed to is the thing §17 exists to prevent.
    """
    before, after = str(predecessor or "").upper(), str(successor or "").upper()
    if not before or not after:
        raise DraftError("A link needs something to depend on and something "
                         "to depend.")
    if before == after:
        raise DraftError("Something cannot depend on itself.")

    first, second = item(plan, before), item(plan, after)
    if first is None:
        raise DraftError(f"There is nothing called {before} in this plan.")
    if second is None:
        raise DraftError(f"There is nothing called {after} in this plan.")

    kind = _one_of(dependency_type, DEPENDENCY_TYPES, "Dependency type",
                   DEP_FINISH_TO_START)
    for existing in links_of(plan):
        if _dep_key(existing) == (before, after):
            raise DraftError(
                f"{before} and {after} are already linked.")

    ids = _synthetic(plan)
    views = [
        control.DependencyView(
            predecessor_type=kind_of(plan, link["predecessor"]),
            predecessor_id=ids.get(str(link["predecessor"]).upper(), 0),
            successor_type=kind_of(plan, link["successor"]),
            successor_id=ids.get(str(link["successor"]).upper(), 0),
            dependency_type=str(link.get("dependency_type",
                                         DEP_FINISH_TO_START)),
            lag_days=int(link.get("lag_days") or 0))
        for link in links_of(plan)]
    views.append(control.DependencyView(
        predecessor_type=kind_of(plan, before), predecessor_id=ids[before],
        successor_type=kind_of(plan, after), successor_id=ids[after],
        dependency_type=kind, lag_days=int(lag_days or 0)))
    loop = control.cycle(views)
    if loop:
        raise DraftError(
            f"Linking {before} to {after} would make a loop: something would "
            "have to finish before itself. Nothing in the plan was changed.")

    # The date conflict, stated rather than fixed.
    finishes = _as_date(first.get("target_date") or first.get("due_date"),
                        "predecessor end")
    starts = _as_date(second.get("start_date"), "successor start")
    conflict = ""
    adjustment: dict[str, Any] = {}
    # Finish-to-start means the successor starts the day AFTER the
    # predecessor finishes — the same arithmetic `schedule._forward` uses. A
    # successor starting ON the predecessor's finish date is therefore a
    # conflict, and the earlier `<` comparison quietly said it was not.
    if kind == DEP_FINISH_TO_START and finishes and starts \
            and starts < finishes + timedelta(days=1 + int(lag_days or 0)):
        conflict = (
            f"{_label(second)} is currently scheduled to begin on {starts}, "
            f"but {_label(first)} finishes on {finishes}.")
        days = ((finishes + timedelta(days=int(lag_days or 0) + 1))
                - starts).days
        adjustment = _adjustment(plan, after, days, extra=(before, after))

    return {
        "predecessor": before, "successor": after,
        "dependency_type": kind, "lag_days": int(lag_days or 0),
        "sentence": f"This will make {_label(second)} depend on "
                    f"{_label(first)}.",
        "conflict": conflict,
        "adjustment": adjustment,
        "predecessor_label": _label(first),
        "successor_label": _label(second),
    }


# The three date columns a plan row can carry, by what kind of row it is.
_DATE_FIELDS = {
    "MILESTONE": ("start_date", "target_date", "critical_date"),
    "TASK": ("start_date", "due_date", "critical_date"),
}


def downstream(plan: dict[str, Any], code: str, *,
               extra: tuple[str, str] | None = None) -> list[str]:
    """`code` and everything that waits on it, in plan order.

    Used to say what an adjustment would actually move. `extra` is a link that
    does not exist yet, so the preview of a link can include the item it is
    about to constrain.
    """
    edges: dict[str, list[str]] = {}
    pairs = [_dep_key(link) for link in links_of(plan)]
    if extra:
        pairs.append((extra[0].upper(), extra[1].upper()))
    for before, after in pairs:
        edges.setdefault(before, []).append(after)

    seen: set[str] = set()
    queue = [str(code).upper()]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        queue.extend(edges.get(current, ()))
    return [str(row["code"]) for row in catalogue(plan)
            if str(row["code"]).upper() in seen]


def _adjustment(plan: dict[str, Any], code: str, days: int, *,
                extra: tuple[str, str] | None = None) -> dict[str, Any]:
    """Exactly which dates moving `code` by `days` would change.

    Returned, never applied. §11 asks for the impact to be STATED before the
    dependency is created, and for the person to choose between moving the
    dates and keeping them; a function that quietly did the first would make
    the choice meaningless.
    """
    if days <= 0:
        return {}
    moved: list[dict[str, Any]] = []
    for item_code in downstream(plan, code, extra=extra):
        row = item(plan, item_code)
        if row is None:
            continue
        kind = kind_of(plan, item_code)
        shift: dict[str, Any] = {
            "code": item_code, "kind": kind, "label": _label(row)}
        touched = False
        for field_ in _DATE_FIELDS.get(kind, ()):
            was = _as_date(row.get(field_), field_)
            shift[field_] = str(was) if was else ""
            shift[f"new_{field_}"] = (
                str(was + timedelta(days=days)) if was else "")
            touched = touched or bool(was)
        if touched:
            moved.append(shift)
    if not moved:
        return {}
    names = ", ".join(str(row["label"]) for row in moved[:4])
    if len(moved) > 4:
        names += f" and {len(moved) - 4} more"
    return {
        "days": days,
        "items": moved,
        "sentence": (
            f"Moving the dates would push {len(moved)} "
            f"{'item' if len(moved) == 1 else 'items'} out by {days} "
            f"{'day' if days == 1 else 'days'}: {names}."),
    }


def _label(row: dict[str, Any]) -> str:
    return f"{row.get('name') or row.get('title') or row.get('code', '')}"


def previous_task(plan: dict[str, Any], code: str) -> str:
    """The task immediately before this one, for "Link to previous task".

    Within the same milestone and in plan order, because that is what a person
    means by "the previous task" while filling in rows. Returns "" when this
    is the first task under its milestone — there is no previous one, and
    guessing across milestones would link things the person did not mean.
    """
    row = item(plan, code)
    if row is None or not row.get("milestone_code"):
        return ""
    siblings = tasks_of(plan, str(row["milestone_code"]))
    for index, sibling in enumerate(siblings):
        if str(sibling.get("code", "")).upper() == str(code).upper():
            return str(siblings[index - 1]["code"]) if index else ""
    return ""


# ------------------------------------------------------------ completeness


def check(plan: dict[str, Any]) -> Completeness:
    """What this draft still needs, and what merely deserves a look."""
    found = Completeness()
    overview = plan.get("overview") or {}
    governance = plan.get("governance") or {}

    def blocker(scope: str, code: str, message: str, fix: str = "",
                field: str = "") -> None:
        found.notes.append(Note(BLOCKER, scope, code, message, fix, field))

    def warn(scope: str, code: str, message: str, fix: str = "",
             field: str = "") -> None:
        found.notes.append(Note(WARNING, scope, code, message, fix, field))

    # ---- what the project IS
    #
    # Scoped "overview" and "governance" rather than both "project", because
    # the form asks for them on different steps and a step that cannot tell
    # which of its own notes belong to it either blocks on somebody else's
    # question or lets its own through.
    if not str(overview.get("name") or "").strip():
        blocker("overview", "", "The project has no name.",
                "Give it a name a committee would recognise.",
                "overview.name")
    if not str(overview.get("code") or "").strip():
        blocker("overview", "", "The project has no code.",
                "A code is how people refer to it in chat and in exports.",
                "overview.code")
    if not str(overview.get("description") or "").strip():
        warn("overview", "", "There is no overview.",
             "One sentence is enough, and it is what the agent quotes back.",
             "overview.description")
    if not str(overview.get("objective") or "").strip():
        warn("overview", "", "There is no objective.",
             "What has to be true for this to be finished?",
             "overview.objective")

    # ---- who is answerable, and when it runs
    for key, label in (("sponsor_id", "sponsor"), ("manager_id", "manager")):
        if not governance.get(key):
            blocker("governance", "", f"The project has no {label}.",
                    f"Name a {label}: the agent escalates through them.",
                    f"governance.{key}")
    if not governance.get("owner_id"):
        warn("governance", "", "The project has no owner.",
             "Often the manager; say so explicitly and the plan reads better.")
    if not governance.get("escalation_id"):
        blocker("governance", "", "There is nobody to escalate to.",
                "This is the last stop when a task's own escalation owner has "
                "not resolved something.", "governance.escalation_id")
    start = _as_date(governance.get("start_date"), "Project start")
    end = _as_date(governance.get("target_end_date"), "Target completion")
    if not start:
        blocker("governance", "", "The project has no start date.", "",
                "governance.start_date")
    if not end:
        blocker("governance", "", "The project has no target completion "
                "date.", "", "governance.target_end_date")
    if start and end and end < start:
        blocker("governance", "",
                f"The project would finish on {end}, before it starts "
                f"on {start}.", "", "governance.target_end_date")

    # ---- the agentic policy
    agentic = plan.get("agentic") or {}
    try:
        policy_mod.resolve(agentic.get("mode", ""), agentic.get("policy"))
    except policy_mod.PolicyError as exc:
        blocker("agentic", "", f"The monitoring policy is not valid: {exc}",
                "", "agentic.mode")

    # ---- milestones
    milestones = milestones_of(plan)
    if not milestones:
        blocker("milestones", "", "The plan has no milestones.",
                "A project with no milestone has nothing to be judged "
                "against.", "milestones.add")
    seen: set[str] = set()
    for milestone in milestones:
        code = str(milestone.get("code") or "")
        if not code:
            blocker("milestone", "", "A milestone has no code.")
            continue
        if code in seen:
            blocker("milestone", code, f"Two milestones share the code {code}.")
        seen.add(code)
        if not str(milestone.get("name") or "").strip():
            blocker("milestone", code, f"{code} has no name.", "",
                    f"milestone.{code}.name")
        if not milestone.get("owner_id"):
            blocker("milestone", code, f"{code} has no owner.",
                    "Somebody has to be answerable for it.",
                    f"milestone.{code}.owner_id")
        m_start = _as_date(milestone.get("start_date"), "Milestone start")
        m_end = _as_date(milestone.get("target_date"), "Milestone date")
        if not m_end:
            blocker("milestone", code, f"{code} has no target date.", "",
                    f"milestone.{code}.target_date")
        if m_start and m_end and m_end < m_start:
            blocker("milestone", code,
                    f"{code} would end on {m_end}, before it starts on "
                    f"{m_start}.", "", f"milestone.{code}.target_date")
        if m_end and end and m_end > end:
            warn("milestone", code,
                 f"{code} ends on {m_end}, after the project's target "
                 f"completion of {end}.", "", f"milestone.{code}.target_date")
        if m_start and start and m_start < start:
            warn("milestone", code,
                 f"{code} starts on {m_start}, before the project starts "
                 f"on {start}.", "", f"milestone.{code}.start_date")
        if not escalation_for(plan, code)["user_id"]:
            warn("milestone", code, f"{code} has nobody to escalate to.",
                 "", f"milestone.{code}.escalation_id")
        if not tasks_of(plan, code):
            warn("milestone", code, f"{code} has no tasks under it.",
                 "A milestone with no work is a date with nothing behind it.",
                 f"tasks.{code}.add")

    # ---- tasks
    for task in tasks_of(plan):
        code = str(task.get("code") or "")
        if not code:
            blocker("task", "", "A task has no code.")
            continue
        if code in seen:
            blocker("task", code, f"Two items share the code {code}.")
        seen.add(code)
        if not str(task.get("title") or "").strip():
            blocker("task", code, f"{code} has no title.", "",
                    f"task.{code}.title")
        if not task.get("owner_id"):
            blocker("task", code, f"{code} has no owner.",
                    "The agent reminds the owner; a task with none is a task "
                    "nobody is asked about.", f"task.{code}.owner_id")
        due = _as_date(task.get("due_date"), "Task due date")
        if not due:
            blocker("task", code, f"{code} has no due date.", "",
                    f"task.{code}.due_date")
        t_start = _as_date(task.get("start_date"), "Task start")
        if t_start and due and due < t_start:
            blocker("task", code,
                    f"{code} would finish on {due}, before it starts on "
                    f"{t_start}.", "", f"task.{code}.due_date")
        parent = item(plan, str(task.get("milestone_code") or ""))
        if parent is None:
            blocker("task", code, f"{code} is not under any milestone.")
        else:
            m_end = _as_date(parent.get("target_date"), "Milestone date")
            if due and m_end and due > m_end:
                warn("task", code,
                     f"{code} is due on {due}, after its milestone "
                     f"{parent.get('code')} on {m_end}.", "",
                     f"task.{code}.due_date")
        if not str(task.get("description") or "").strip():
            warn("task", code, f"{code} has no description.",
                 "The owner reads this when they are reminded.",
                 f"task.{code}.description")

    # ---- links
    for link in links_of(plan):
        before, after = _dep_key(link)
        if item(plan, before) is None or item(plan, after) is None:
            blocker("link", f"{before}->{after}",
                    f"The link {before} → {after} points at something that is "
                    "no longer in the plan.")
        # A conflict somebody chose to keep is not a mistake, but it is
        # something the person publishing should see once more.
        if str(link.get("notes") or "").strip():
            warn("link", f"{before}->{after}", str(link["notes"]),
                 "Either move the dates or publish knowing they overlap.",
                 f"link.{before}->{after}")
    ids = _synthetic(plan)
    views = [
        control.DependencyView(
            predecessor_type=kind_of(plan, link["predecessor"]),
            predecessor_id=ids.get(str(link["predecessor"]).upper(), 0),
            successor_type=kind_of(plan, link["successor"]),
            successor_id=ids.get(str(link["successor"]).upper(), 0),
            dependency_type=str(link.get("dependency_type",
                                         DEP_FINISH_TO_START)),
            lag_days=int(link.get("lag_days") or 0))
        for link in links_of(plan)]
    if control.cycle(views):
        blocker("link", "", "The dependencies contain a loop.")

    return found


# ------------------------------------------------------------- persistence


def _key() -> str:
    """An unguessable handle for a draft.

    Drafts are addressed by key rather than by id in the URL and in chat.
    A plan being written names people, dates and money before anybody has
    decided it is real, and a sequential id invites walking the range.
    """
    return secrets.token_urlsafe(12)


def _may_touch(draft: PlannerDraft, principal: Any) -> None:
    """A draft belongs to whoever started it, plus platform administrators.

    There are no participants on a draft — there is no project yet to be a
    participant of — so this is the whole rule. Sharing a draft is publishing
    it, which is the point of publishing it.
    """
    actor = getattr(principal, "user_id", None)
    if acl.is_admin(principal):
        return
    if draft.created_by is not None and actor is not None \
            and int(draft.created_by) == int(actor):
        return
    raise acl.ProjectDenied("This draft belongs to somebody else.")


def create(session: Any, principal: Any, *, name: str = "",
           plan: dict[str, Any] | None = None,
           source: str = SOURCE_UI) -> PlannerDraft:
    """Start a plan. Nothing about it is required yet."""
    actor = getattr(principal, "user_id", None)
    document = plan if plan is not None else empty()
    if name:
        document.setdefault("overview", {})["name"] = str(name)[:200]
        if not document["overview"].get("code"):
            document["overview"]["code"] = suggest_code(name)
    row = PlannerDraft(
        key=_key(), name=str(document.get("overview", {}).get("name") or "")[:200],
        code=str(document.get("overview", {}).get("code") or "")[:40],
        status=DRAFT_DRAFTING, step=STEP_OVERVIEW, plan=document,
        created_by=actor, updated_by=actor, version=1)
    session.add(row)
    session.flush()
    service.audit(session, "PLANNER_DRAFT_CREATED", actor_id=actor,
                  project_id=None, source=source, draft=row.key)
    return row


def load(session: Any, principal: Any, key: str) -> PlannerDraft:
    row = session.execute(
        select(PlannerDraft).where(PlannerDraft.key == str(key))
    ).scalar_one_or_none()
    if row is None:
        raise acl.ProjectNotFound(f"No draft {key}.")
    _may_touch(row, principal)
    return row


def list_for(session: Any, principal: Any, *, status: str = "",
             limit: int = 100) -> list[PlannerDraft]:
    """The drafts this person may see, newest first, bounded.

    Bounded because it was not, and an administrator on an installation that
    has been running for a year is every draft anybody ever started, in one
    response, rendered in one list. Newest first is the ordering that makes
    a limit safe: the ones you are working on are the ones you get.
    """
    query = select(PlannerDraft).order_by(PlannerDraft.updated_at.desc())
    if status:
        query = query.where(PlannerDraft.status == str(status).upper())
    if not acl.is_admin(principal):
        actor = getattr(principal, "user_id", None)
        if actor is None:
            return []
        query = query.where(PlannerDraft.created_by == int(actor))
    return list(session.execute(query.limit(max(1, int(limit or 100)))
                                ).scalars())


def save(session: Any, principal: Any, draft: PlannerDraft, *,
         plan: dict[str, Any] | None = None, step: str = "",
         status: str = "", expected_version: int | None = None,
         source: str = SOURCE_UI) -> PlannerDraft:
    """Write the document back, refusing a write built on a stale read.

    The same optimistic-concurrency rule the planner rows use, for the same
    reason: the Copilot writes this document from chat while a person may be
    editing the milestone table in another tab.
    """
    if draft.status == DRAFT_PUBLISHED:
        raise DraftError(
            "This draft has already been published. Edit the project itself.")
    actor = getattr(principal, "user_id", None)
    if expected_version is not None \
            and int(expected_version) != int(draft.version or 1):
        raise service.StaleWrite(
            f"This draft was changed while you were editing it (you have "
            f"version {expected_version}, it is now {draft.version}). Reload "
            "and apply your change again.")
    if plan is not None:
        draft.plan = plan
        overview = plan.get("overview") or {}
        draft.name = str(overview.get("name") or "")[:200]
        draft.code = str(overview.get("code") or "")[:40]
    if step:
        draft.step = _one_of(step, DRAFT_STEPS, "Draft step", STEP_OVERVIEW)
    if status:
        draft.status = _one_of(status, DRAFT_STATUSES, "Draft status",
                               DRAFT_DRAFTING)
    draft.version = int(draft.version or 1) + 1
    draft.updated_by = actor
    draft.updated_at = datetime.now(UTC)
    session.flush()
    return draft


def discard(session: Any, principal: Any, key: str, *,
            source: str = SOURCE_UI) -> None:
    """Throw a draft away. A published one is kept: it is the approval record."""
    row = load(session, principal, key)
    if row.status == DRAFT_PUBLISHED:
        raise DraftError(
            "A published draft is the record of what was approved and is not "
            "deleted. Archive the project instead.")
    actor = getattr(principal, "user_id", None)
    service.audit(session, "PLANNER_DRAFT_DISCARDED", actor_id=actor,
                  project_id=None, source=source, draft=row.key)
    session.delete(row)
    session.flush()


# ---------------------------------------------------------------- the writer


def _next_milestone_code(plan: dict[str, Any]) -> str:
    used = {str(m.get("code", "")).upper() for m in milestones_of(plan)}
    index = 1
    while milestone_code(index) in used:
        index += 1
    return milestone_code(index)


def _next_task_code(plan: dict[str, Any], milestone: str) -> str:
    used = {str(t.get("code", "")).upper() for t in tasks_of(plan)}
    index = 1
    while task_code(milestone, index) in used:
        index += 1
    return task_code(milestone, index)


def _user(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DraftError(f"{value!r} is not a person I can identify.") from exc


def _people(plan: dict[str, Any]) -> set[int]:
    """Everybody the plan names, so publish can put them on the project."""
    found: set[int] = set()
    governance = plan.get("governance") or {}
    for key in ("sponsor_id", "manager_id", "owner_id", "escalation_id"):
        if governance.get(key):
            found.add(int(governance[key]))
    for row in [*milestones_of(plan), *tasks_of(plan)]:
        for key in ("owner_id", "reviewer_id", "escalation_id"):
            if row.get(key):
                found.add(int(row[key]))
        for contributor in row.get("contributor_ids") or []:
            found.add(int(contributor))
    return found


#: Fields a milestone carries in the draft, and how to read each one.
_MILESTONE_FIELDS: dict[str, str] = {
    "name": "text", "description": "text", "owner_id": "user",
    "escalation_id": "user", "start_date": "date", "target_date": "date",
    "critical_date": "date", "priority": "priority", "critical": "flag",
    "status": "milestone_status",
}

#: Everything a task can carry in a plan. `status`, `percent_complete`,
#: `blocked` and `blocker_reason` are here because a plan is not always
#: written before the work starts: a programme picked up mid-flight has tasks
#: that are already in progress, already blocked, and already carry a reason.
#: Publishing writes them straight through, so the project opens in the state
#: the plan described rather than pretending everything begins at zero.
_TASK_FIELDS: dict[str, str] = {
    "title": "text", "description": "text", "owner_id": "user",
    "reviewer_id": "user", "escalation_id": "user", "start_date": "date",
    "due_date": "date", "critical_date": "date", "priority": "priority",
    "effort_days": "number", "critical": "flag", "next_step": "text",
    "status": "task_status", "weight": "weight",
    "percent_complete": "percent", "blocked": "flag",
    "blocker_reason": "text",
}


def _coerce(kind: str, key: str, value: Any) -> Any:
    if kind == "date":
        found = _as_date(value, key.replace("_", " ").capitalize())
        return found.isoformat() if found else None
    if kind == "user":
        return _user(value)
    if kind == "priority":
        return _one_of(value, PRIORITIES, "Priority", PRIORITY_MEDIUM)
    if kind == "flag":
        return bool(value)
    if kind == "number":
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise DraftError(f"{key} must be a number of days.") from exc
    if kind == "percent":
        if value in (None, ""):
            return 0
        try:
            found = int(value)
        except (TypeError, ValueError) as exc:
            raise DraftError(f"{key} must be a whole percentage.") from exc
        if not 0 <= found <= 100:
            raise DraftError(f"{key} must be between 0 and 100.")
        return found
    if kind == "weight":
        if value in (None, ""):
            return 1.0
        try:
            found = float(value)
        except (TypeError, ValueError) as exc:
            raise DraftError(f"{key} must be a number.") from exc
        if found <= 0:
            raise DraftError(
                "A task weight of zero would remove it from the progress "
                "calculation without removing it from the plan.")
        return found
    if kind == "task_status":
        return _one_of(value, TASK_STATUSES, "Task status", "NOT_STARTED")
    if kind == "milestone_status":
        return _one_of(value, MILESTONE_STATUSES, "Milestone status",
                       "PENDING")
    return str(value or "")


def _no_strays(payload: dict[str, Any], allowed: set[str],
               what: str) -> None:
    """Refuse a field this command does not know, instead of dropping it.

    A payload key nobody reads is the quietest bug in a form: the screen
    holds one value, the draft holds another, and the panel computed from
    the draft is then correct about a plan the person cannot see. Better a
    422 naming the field, in the test that sent it.
    """
    strays = sorted(set(payload) - allowed)
    if strays:
        raise DraftError(
            f"{what} does not have a field called {strays[0]}."
            + (f" ({len(strays)} unknown fields in all.)"
               if len(strays) > 1 else ""))


def _write(row: dict[str, Any], fields: dict[str, str],
           payload: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for key, kind in fields.items():
        if key not in payload:
            continue
        new = _coerce(kind, key, payload[key])
        if row.get(key) != new:
            row[key] = new
            changed.append(key)
    return changed


#: Everything chat and the panel are allowed to do to a draft. Named
#: explicitly rather than derived from the payload, so a chat turn cannot
#: reach a mutation nobody wrote a screen for.
COMMANDS: tuple[str, ...] = (
    "set_overview", "set_governance", "set_agentic",
    "add_milestone", "update_milestone", "remove_milestone", "move_milestone",
    "add_task", "update_task", "remove_task",
    "add_link", "remove_link", "set_step",
)


def apply(session: Any, principal: Any, key: str, command: str,
          payload: dict[str, Any] | None = None, *,
          expected_version: int | None = None,
          source: str = SOURCE_UI) -> dict[str, Any]:
    """The one way a draft changes.

    Chat resolves an instruction into a command and calls this; the milestone
    panel calls this; the task table calls this. There is no second path, so
    a rule added here — a code that must not be regenerated, an escalation
    that must be inherited — holds for every way in.
    """
    draft = load(session, principal, key)
    if draft.status == DRAFT_PUBLISHED:
        raise DraftError(
            "This draft has already been published. Edit the project itself.")
    verb = str(command or "").strip().lower()
    if verb not in COMMANDS:
        raise DraftError(
            f"I do not know how to {command!r}. I can change the overview, "
            "the governance, the way the agent works, milestones, tasks and "
            "the links between them.")
    data = dict(payload or {})
    # A copy, so a command that fails halfway leaves the stored plan untouched.
    plan = _copy(draft.plan or empty())
    outcome = _COMMANDS[verb](plan, data)

    # Where the command THINKS you are next, returned to the caller — and
    # written down only by `set_step`, which is the one command that means
    # "I have moved". A field-setting command that moved the stored step
    # moved it out from under the person: choose an agentic policy and the
    # draft recorded you on the milestones, so reopening the plan put you a
    # step past the one you were working on.
    suggested = str(outcome.get("step", "") or "")
    save(session, principal, draft, plan=plan,
         step=suggested if verb == "set_step" else "",
         expected_version=expected_version, source=source)
    actor = getattr(principal, "user_id", None)
    service.audit(session, "PLANNER_DRAFT_CHANGED", actor_id=actor,
                  project_id=None, source=source, draft=draft.key,
                  command=verb, subject=str(outcome.get("code", "")))
    return {"draft": to_dict(draft), **outcome}


def _copy(plan: dict[str, Any]) -> dict[str, Any]:
    """A deep copy, so a command that raises halfway leaves the stored plan
    exactly as it was rather than half-changed."""
    return copy.deepcopy(dict(plan))


#: What each of the two project-level commands accepts. Anything else is a
#: mistake somebody should be told about; see `_no_strays`.
_OVERVIEW_FIELDS = {"name", "code", "description", "objective"}
_GOVERNANCE_FIELDS = {"sponsor_id", "manager_id", "owner_id", "escalation_id",
                      "start_date", "target_end_date", "priority", "status",
                      "reporting_cadence"}


def _cmd_overview(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, _OVERVIEW_FIELDS, "The overview")
    overview = plan.setdefault("overview", {})
    for field_ in ("name", "description", "objective"):
        if field_ in data:
            overview[field_] = str(data[field_] or "")[:4000]
    if "code" in data:
        # An empty code that was SENT is a code somebody deleted. Treating it
        # as "no opinion" — which is what happens when the only test is
        # truthiness — makes the field impossible to clear: the box empties,
        # the draft keeps the old value, and the two disagree until somebody
        # reloads and finds their deletion undone.
        wanted = str(data["code"] or "").strip()
        overview["code"] = (service.check_code(wanted, "Project code")
                            if wanted else "")
    elif overview.get("name") and not overview.get("code"):
        overview["code"] = suggest_code(overview["name"])
    if overview.get("name"):
        overview["name"] = overview["name"][:200]
    return {"step": STEP_GOVERNANCE, "code": overview.get("code", "")}


def _cmd_governance(plan: dict[str, Any],
                    data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, _GOVERNANCE_FIELDS, "Governance")
    governance = plan.setdefault("governance", {})
    for field_ in ("sponsor_id", "manager_id", "owner_id", "escalation_id"):
        if field_ in data:
            governance[field_] = _user(data[field_])
    for field_ in ("start_date", "target_end_date"):
        if field_ in data:
            found = _as_date(data[field_], field_.replace("_", " "))
            governance[field_] = found.isoformat() if found else None
    if "priority" in data:
        governance["priority"] = _one_of(data["priority"], PRIORITIES,
                                         "Priority", PRIORITY_MEDIUM)
    if "status" in data:
        governance["status"] = _one_of(data["status"], PROJECT_STATUSES,
                                       "Project status", "ACTIVE")
    if "reporting_cadence" in data:
        governance["reporting_cadence"] = _one_of(
            data["reporting_cadence"], CADENCES, "Reporting cadence",
            CADENCE_WEEKLY)
    start = _as_date(governance.get("start_date"), "Project start")
    end = _as_date(governance.get("target_end_date"), "Target completion")
    if start and end and end < start:
        raise DraftError(
            f"The project would finish on {end}, before it starts on {start}.")
    return {"step": STEP_AGENTIC}


def _cmd_agentic(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    mode = str(data.get("mode") or plan.get("agentic", {}).get("mode")
               or policy_mod.MODE_STANDARD).upper()
    document = data.get("policy")
    if document is None:
        document = plan.get("agentic", {}).get("policy") or {}
    agentic = policy_mod.resolve(mode, document)  # raises PolicyError if wrong
    plan["agentic"] = {"mode": agentic.mode,
                       "policy": dict(document) if document else {}}
    return {"step": STEP_MILESTONES,
            "sentence": policy_mod.sentence(agentic),
            "agentic": policy_mod.describe(agentic)}


def _cmd_add_milestone(plan: dict[str, Any],
                       data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, set(_MILESTONE_FIELDS), "A milestone")
    if not str(data.get("name") or "").strip():
        raise DraftError("A milestone needs a name.")
    row: dict[str, Any] = {"code": _next_milestone_code(plan),
                           "priority": PRIORITY_MEDIUM, "critical": False}
    _write(row, _MILESTONE_FIELDS, data)
    _milestone_dates(row)
    plan.setdefault("milestones", []).append(row)
    return {"step": STEP_MILESTONES, "code": row["code"], "milestone": row}


def _milestone_dates(row: dict[str, Any]) -> None:
    start = _as_date(row.get("start_date"), "Milestone start")
    end = _as_date(row.get("target_date"), "Milestone target date")
    critical = _as_date(row.get("critical_date"), "Milestone critical date")
    if start and end and end < start:
        raise DraftError(
            f"{row.get('code', 'The milestone')} would end on {end}, before "
            f"it starts on {start}.")
    if critical and start and critical < start:
        raise DraftError(
            f"{row.get('code', 'The milestone')} cannot have a critical date "
            f"of {critical}, before it starts on {start}.")
    if critical and end and critical > end:
        raise DraftError(
            f"{row.get('code', 'The milestone')} cannot have a critical date "
            f"of {critical}, after it is due on {end}.")


def _cmd_update_milestone(plan: dict[str, Any],
                          data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, set(_MILESTONE_FIELDS) | {"code"}, "A milestone")
    code = str(data.get("code") or "").upper()
    row = item(plan, code)
    if row is None or kind_of(plan, code) != ENTITY_MILESTONE:
        raise DraftError(f"There is no milestone called {code} in this plan.")
    changed = _write(row, _MILESTONE_FIELDS, data)
    _milestone_dates(row)
    return {"step": STEP_MILESTONES, "code": code, "changed": changed,
            "milestone": row}


def _cmd_remove_milestone(plan: dict[str, Any],
                          data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("code") or "").upper()
    row = item(plan, code)
    if row is None or kind_of(plan, code) != ENTITY_MILESTONE:
        raise DraftError(f"There is no milestone called {code} in this plan.")
    doomed = {str(t.get("code", "")).upper() for t in tasks_of(plan, code)}
    doomed.add(code)
    plan["milestones"] = [m for m in milestones_of(plan)
                          if str(m.get("code", "")).upper() != code]
    plan["tasks"] = [t for t in tasks_of(plan)
                     if str(t.get("milestone_code", "")).upper() != code]
    # Links into or out of anything that just went are removed with it,
    # rather than left pointing at nothing for the completeness check to find.
    plan["links"] = [link for link in links_of(plan)
                     if not set(_dep_key(link)) & doomed]
    return {"step": STEP_MILESTONES, "code": code,
            "removed_tasks": sorted(doomed - {code})}


def _cmd_move_milestone(plan: dict[str, Any],
                        data: dict[str, Any]) -> dict[str, Any]:
    """Move a milestone up or down, and renumber everything with it.

    Renumbering codes is normally the wrong thing to do — a code is how a task
    is referred to in an export and in whatever somebody has already written
    down — and `update_task` deliberately refuses to do it. A DRAFT is the one
    place where it is right: nothing has been published, nobody has quoted
    M03 in an email, and a milestone list where M03 sits above M01 is a plan
    that reads wrong to the person writing it.

    So this renumbers the milestones, the tasks under them and every link, in
    one step, and `apply` refuses to run on a published draft at all.
    """
    code = str(data.get("code") or "").upper()
    rows = milestones_of(plan)
    order = [str(r.get("code", "")).upper() for r in rows]
    if code not in order:
        raise DraftError(f"There is no milestone called {code} in this plan.")
    direction = str(data.get("direction") or "").strip().lower()
    if direction not in ("up", "down"):
        raise DraftError("Say whether to move it up or down.")

    at = order.index(code)
    to = at - 1 if direction == "up" else at + 1
    if not 0 <= to < len(rows):
        return {"step": STEP_MILESTONES, "code": code, "moved": False}
    rows[at], rows[to] = rows[to], rows[at]

    # New codes, in the new order, and the map from old to new.
    renamed: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        was = str(row.get("code", "")).upper()
        now = milestone_code(index)
        renamed[was] = now
        row["code"] = now
    plan["milestones"] = rows

    tasks = tasks_of(plan)
    counts: dict[str, int] = {}
    for task in tasks:
        parent = renamed.get(str(task.get("milestone_code", "")).upper(), "")
        if not parent:
            continue
        counts[parent] = counts.get(parent, 0) + 1
        was = str(task.get("code", "")).upper()
        now = task_code(parent, counts[parent])
        renamed[was] = now
        task["milestone_code"] = parent
        task["code"] = now

    for link in links_of(plan):
        for end in ("predecessor", "successor"):
            was = str(link.get(end, "")).upper()
            link[end] = renamed.get(was, was)
    return {"step": STEP_MILESTONES, "code": renamed.get(code, code),
            "moved": True, "renamed": renamed}


def _cmd_add_task(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, set(_TASK_FIELDS) | {"milestone_code", "contributor_ids"},
               "A task")
    milestone = str(data.get("milestone_code") or "").upper()
    if not milestone or kind_of(plan, milestone) != ENTITY_MILESTONE \
            or item(plan, milestone) is None:
        raise DraftError(
            "A task belongs to a milestone. Say which one, using its code.")
    if not str(data.get("title") or "").strip():
        raise DraftError("A task needs a title.")
    row: dict[str, Any] = {
        "code": _next_task_code(plan, milestone),
        "milestone_code": milestone, "priority": PRIORITY_MEDIUM,
        "critical": False, "contributor_ids": []}
    _write(row, _TASK_FIELDS, data)
    if data.get("contributor_ids") is not None:
        row["contributor_ids"] = [int(c) for c in data["contributor_ids"] if c]
    _task_dates(row)
    plan.setdefault("tasks", []).append(row)

    outcome: dict[str, Any] = {"step": STEP_TASKS, "code": row["code"],
                               "task": row}
    # "Link to previous task" is offered rather than applied: the person asked
    # for a task, not for a dependency, and §17 says a link states itself
    # before it exists.
    previous = previous_task(plan, row["code"])
    if previous:
        outcome["suggest_link"] = {"predecessor": previous,
                                   "successor": row["code"]}
    return outcome


def _task_dates(row: dict[str, Any]) -> None:
    start = _as_date(row.get("start_date"), "Task start")
    due = _as_date(row.get("due_date"), "Task due date")
    critical = _as_date(row.get("critical_date"), "Task critical date")
    if start and due and due < start:
        raise DraftError(
            f"{row.get('code', 'The task')} would finish on {due}, before it "
            f"starts on {start}.")
    if critical and due and critical > due:
        raise DraftError(
            f"{row.get('code', 'The task')} cannot have a critical date of "
            f"{critical}, after it is due on {due}.")


def _cmd_update_task(plan: dict[str, Any],
                     data: dict[str, Any]) -> dict[str, Any]:
    _no_strays(data, set(_TASK_FIELDS) | {"code", "milestone_code",
                                          "contributor_ids"}, "A task")
    code = str(data.get("code") or "").upper()
    row = item(plan, code)
    if row is None or kind_of(plan, code) != ENTITY_TASK:
        raise DraftError(f"There is no task called {code} in this plan.")
    changed = _write(row, _TASK_FIELDS, data)
    if data.get("contributor_ids") is not None:
        row["contributor_ids"] = [int(c) for c in data["contributor_ids"] if c]
        changed.append("contributor_ids")
    if data.get("milestone_code"):
        moved = str(data["milestone_code"]).upper()
        if kind_of(plan, moved) != ENTITY_MILESTONE or item(plan, moved) is None:
            raise DraftError(f"There is no milestone called {moved}.")
        # The code is NOT regenerated to match the new milestone. It is how
        # this task is referred to in chat, in the export and in whatever
        # somebody has already written down.
        row["milestone_code"] = moved
        changed.append("milestone_code")
    _task_dates(row)
    return {"step": STEP_TASKS, "code": code, "changed": changed, "task": row}


def _cmd_remove_task(plan: dict[str, Any],
                     data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("code") or "").upper()
    row = item(plan, code)
    if row is None or kind_of(plan, code) != ENTITY_TASK:
        raise DraftError(f"There is no task called {code} in this plan.")
    plan["tasks"] = [t for t in tasks_of(plan)
                     if str(t.get("code", "")).upper() != code]
    plan["links"] = [link for link in links_of(plan)
                     if code not in _dep_key(link)]
    return {"step": STEP_TASKS, "code": code}


def _cmd_add_link(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Link two things, having been told what to do about the dates.

    `adjust` moves the successor and everything behind it by exactly the
    number of days the preview named. Without it the dates stay where the
    person put them and the conflict is written onto the link, so it survives
    into the project instead of being forgotten between the preview and the
    publish. There is no third behaviour: this function never moves a date
    that was not asked for.
    """
    preview_ = link_preview(
        plan, str(data.get("predecessor") or ""),
        str(data.get("successor") or ""),
        dependency_type=str(data.get("dependency_type")
                            or DEP_FINISH_TO_START),
        lag_days=int(data.get("lag_days") or 0))

    adjustment = preview_.get("adjustment") or {}
    moved: list[str] = []
    if data.get("adjust"):
        if not adjustment:
            raise DraftError(
                "There is no date conflict on this link, so there is nothing "
                "to adjust.")
        for shift in adjustment["items"]:
            row = item(plan, str(shift["code"]))
            if row is None:
                continue
            for field_ in _DATE_FIELDS.get(str(shift["kind"]), ()):
                if shift.get(f"new_{field_}"):
                    row[field_] = shift[f"new_{field_}"]
            moved.append(str(shift["code"]))

    notes = str(data.get("notes") or "")
    if not notes and preview_["conflict"] and not data.get("adjust"):
        notes = f"Date conflict kept and flagged. {preview_['conflict']}"

    link: dict[str, Any] = {
        "predecessor": preview_["predecessor"],
        "successor": preview_["successor"],
        "dependency_type": preview_["dependency_type"],
        "lag_days": preview_["lag_days"]}
    # Only carried when there is something to carry. A link with an empty
    # note is the ordinary case, and writing the key anyway would put a blank
    # field in every plan document ever exported.
    if notes:
        link["notes"] = notes
    plan.setdefault("links", []).append(link)
    return {"step": STEP_DEPENDENCIES, "code": preview_["successor"],
            "link": preview_, "moved": moved}


def _cmd_remove_link(plan: dict[str, Any],
                     data: dict[str, Any]) -> dict[str, Any]:
    wanted = (str(data.get("predecessor") or "").upper(),
              str(data.get("successor") or "").upper())
    kept = [link for link in links_of(plan) if _dep_key(link) != wanted]
    if len(kept) == len(links_of(plan)):
        raise DraftError(
            f"{wanted[1]} does not currently wait on {wanted[0]}.")
    plan["links"] = kept
    return {"step": STEP_DEPENDENCIES, "code": wanted[1]}


def _cmd_set_step(plan: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return {"step": _one_of(data.get("step"), DRAFT_STEPS, "Draft step",
                            STEP_OVERVIEW)}


_COMMANDS = {
    "set_overview": _cmd_overview,
    "set_governance": _cmd_governance,
    "set_agentic": _cmd_agentic,
    "add_milestone": _cmd_add_milestone,
    "update_milestone": _cmd_update_milestone,
    "remove_milestone": _cmd_remove_milestone,
    "move_milestone": _cmd_move_milestone,
    "add_task": _cmd_add_task,
    "update_task": _cmd_update_task,
    "remove_task": _cmd_remove_task,
    "add_link": _cmd_add_link,
    "remove_link": _cmd_remove_link,
    "set_step": _cmd_set_step,
}


# ------------------------------------------------------------------ preview


def people_named(session: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Everybody this plan puts a name to, resolved once.

    The form needs display names for the owners, sponsors and escalation
    contacts it is showing back. Sending the whole staff directory to do that
    is what made the person-pickers unusable on a large installation; this is
    the ten or twenty people the plan actually mentions.
    """
    wanted = _people(plan)
    if not wanted:
        return []
    # The same by-id lookup the pickers and the agent use, in the same
    # projection. A second query here would be a second place for the shape
    # of a person to drift, and the form and the escalation would then be
    # describing the same colleague differently.
    from backend.services import people as directory

    found = directory.by_ids(session, wanted, projection=directory.CONTACT)
    return [found[user_id] for user_id in sorted(found)]


def to_dict(draft: PlannerDraft) -> dict[str, Any]:
    return {
        "key": draft.key, "name": draft.name, "code": draft.code,
        "status": draft.status, "step": draft.step,
        "plan": draft.plan or empty(), "version": int(draft.version or 1),
        "project_id": draft.project_id,
        "created_by": draft.created_by, "updated_by": draft.updated_by,
        "updated_at": (draft.updated_at.isoformat()
                       if draft.updated_at else ""),
    }


def preview(plan: dict[str, Any]) -> dict[str, Any]:
    """Everything that would be created, in the shape a person reads it.

    Shown in full before publish and never abbreviated: the point of the
    confirmation step is that somebody sees the whole plan once, and a preview
    that hides the fifth milestone is a confirmation of something else.
    """
    governance = plan.get("governance") or {}
    agentic = policy_mod.resolve((plan.get("agentic") or {}).get("mode", ""),
                                 (plan.get("agentic") or {}).get("policy"))
    milestones: list[dict[str, Any]] = []
    for milestone in milestones_of(plan):
        code = str(milestone.get("code", ""))
        milestones.append({
            **milestone,
            "escalation": escalation_for(plan, code),
            "tasks": [{**task, "escalation": escalation_for(
                plan, str(task.get("code", "")))}
                for task in tasks_of(plan, code)],
        })
    links = []
    for link in links_of(plan):
        before, after = _dep_key(link)
        first, second = item(plan, before), item(plan, after)
        links.append({
            **link,
            "sentence": (f"{_label(second) if second else after} waits for "
                         f"{_label(first) if first else before}"),
        })
    return {
        "overview": plan.get("overview") or {},
        "governance": governance,
        "agentic": {"mode": agentic.mode, "label": agentic.label,
                    "sentence": policy_mod.sentence(agentic),
                    **policy_mod.describe(agentic)},
        "milestones": milestones,
        "links": links,
        "schedule": timeline(plan),
        "totals": {"milestones": len(milestones_of(plan)),
                   "tasks": len(tasks_of(plan)),
                   "links": len(links_of(plan)),
                   "people": len(_people(plan))},
        "completeness": check(plan).to_dict(),
    }


def as_engine_plan(plan: dict[str, Any]) -> control.Plan:
    """The draft in the shape the scheduling engine reads.

    Ids are synthetic and stable within the call — the engine needs integers
    and a draft has none — but everything else is the plan as written, so the
    critical path shown before publish is computed by the same code that
    computes it afterwards rather than by a second implementation.
    """
    ids = _synthetic(plan)
    governance = plan.get("governance") or {}
    return control.Plan(
        project_id=0,
        code=str((plan.get("overview") or {}).get("code") or ""),
        name=str((plan.get("overview") or {}).get("name") or ""),
        status=str(governance.get("status") or "ACTIVE"),
        target_end_date=_as_date(governance.get("target_end_date"),
                                 "Target completion"),
        milestones=[
            control.MilestoneView(
                id=ids.get(str(row.get("code", "")).upper(), 0),
                code=str(row.get("code", "")),
                name=str(row.get("name") or ""),
                status=str(row.get("status") or "PENDING"),
                target_date=_as_date(row.get("target_date"), "Milestone date"),
                owner_id=_user(row.get("owner_id")),
                critical=bool(row.get("critical")))
            for row in milestones_of(plan)],
        tasks=[
            control.TaskView(
                id=ids.get(str(row.get("code", "")).upper(), 0),
                code=str(row.get("code", "")),
                title=str(row.get("title") or ""),
                status=str(row.get("status") or "NOT_STARTED"),
                percent_complete=int(row.get("percent_complete") or 0),
                weight=float(row.get("weight") or 1),
                due_date=_as_date(row.get("due_date"), "Task due date"),
                start_date=_as_date(row.get("start_date"), "Task start"),
                owner_id=_user(row.get("owner_id")),
                critical=bool(row.get("critical")),
                blocked=bool(row.get("blocked")),
                blocker_reason=str(row.get("blocker_reason") or ""),
                milestone_id=ids.get(
                    str(row.get("milestone_code", "")).upper()),
                effort_days=(int(row["effort_days"])
                             if row.get("effort_days") else None))
            for row in tasks_of(plan)],
        dependencies=[
            control.DependencyView(
                predecessor_type=kind_of(plan, str(link["predecessor"])),
                predecessor_id=ids.get(str(link["predecessor"]).upper(), 0),
                successor_type=kind_of(plan, str(link["successor"])),
                successor_id=ids.get(str(link["successor"]).upper(), 0),
                dependency_type=str(link.get("dependency_type")
                                    or DEP_FINISH_TO_START),
                lag_days=int(link.get("lag_days") or 0))
            for link in links_of(plan)])


def timeline(plan: dict[str, Any]) -> dict[str, Any]:
    """The dates and the critical path this plan implies, before it exists.

    §12 asks the preview to show the timeline. Returned as the engine's own
    dictionary, including `cannot_because` when there is not enough in the
    plan to place anything: an empty timeline that said nothing would read as
    a project with no schedule rather than as a plan that still needs dates.
    """
    governance = plan.get("governance") or {}
    return schedule.compute(
        as_engine_plan(plan),
        project_start=_as_date(governance.get("start_date"),
                               "Project start")).to_dict()


# ------------------------------------------------------------------ publish


def publish(session: Any, principal: Any, key: str, *,
            source: str = SOURCE_UI) -> PlannerProject:
    """Turn the draft into a real project, or into nothing at all.

    Every row is created through `service`, so this path has exactly the
    permission checks, validation, versioning, audit trail, update history and
    event signalling the UI has. The whole thing runs inside a savepoint: a
    publication that fails on the fortieth task leaves no project behind for
    somebody to find on Monday and start working on.
    """
    draft = load(session, principal, key)
    if draft.status == DRAFT_PUBLISHED:
        raise DraftError(
            f"This draft was already published as project "
            f"{draft.code or draft.project_id}.")
    plan = dict(draft.plan or empty())
    complete = check(plan)
    if not complete.publishable:
        raise DraftError(
            "This plan is not ready to publish: "
            + " ".join(note.message for note in complete.blockers))

    overview = plan.get("overview") or {}
    governance = plan.get("governance") or {}
    agentic = policy_mod.resolve((plan.get("agentic") or {}).get("mode", ""),
                                 (plan.get("agentic") or {}).get("policy"))
    actor = getattr(principal, "user_id", None)

    with session.begin_nested():
        project = service.create_project(
            session, principal,
            code=str(overview.get("code") or ""),
            name=str(overview.get("name") or ""),
            description=str(overview.get("description") or ""),
            objective=str(overview.get("objective") or ""),
            status=str(governance.get("status") or "ACTIVE"),
            priority=str(governance.get("priority") or PRIORITY_MEDIUM),
            sponsor_id=governance.get("sponsor_id"),
            manager_id=governance.get("manager_id"),
            start_date=governance.get("start_date"),
            target_end_date=governance.get("target_end_date"),
            reporting_cadence=str(governance.get("reporting_cadence")
                                  or CADENCE_WEEKLY),
            reminder_days=list(agentic.policy.reminder_days),
            stale_after_days=agentic.policy.stale_after_days,
            source=source)

        # The four columns `create_project` does not take, written here rather
        # than added to its signature: they are Copilot concepts, and every
        # existing caller would have to learn about them.
        project.owner_id = _user(governance.get("owner_id"))
        project.escalation_id = _user(governance.get("escalation_id"))
        policy_mod.stamp(project, agentic,
                         (plan.get("agentic") or {}).get("policy"))
        session.flush()
        service.audit(session, "PLANNER_AGENTIC_SET", actor_id=actor,
                      project_id=int(project.id), source=source,
                      mode=agentic.mode,
                      escalation=project.escalation_id,
                      owner=project.owner_id)

        _seat_everybody(session, principal, project, plan, source)

        milestone_ids: dict[str, int] = {}
        for milestone in milestones_of(plan):
            code = str(milestone.get("code", ""))
            row = service.create_milestone(
                session, principal, int(project.id), code=code,
                name=str(milestone.get("name") or ""),
                description=str(milestone.get("description") or ""),
                owner_id=milestone.get("owner_id"),
                escalation_id=milestone.get("escalation_id"),
                start_date=milestone.get("start_date"),
                target_date=milestone.get("target_date"),
                critical_date=milestone.get("critical_date"),
                priority=str(milestone.get("priority") or PRIORITY_MEDIUM),
                critical=bool(milestone.get("critical")),
                status=str(milestone.get("status") or "PENDING"),
                source=source)
            milestone_ids[code.upper()] = int(row.id)

        task_ids: dict[str, int] = {}
        for task in tasks_of(plan):
            code = str(task.get("code", ""))
            row = service.create_task(
                session, principal, int(project.id), code=code,
                milestone_id=milestone_ids.get(
                    str(task.get("milestone_code", "")).upper()),
                title=str(task.get("title") or ""),
                description=str(task.get("description") or ""),
                owner_id=task.get("owner_id"),
                reviewer_id=task.get("reviewer_id"),
                escalation_id=task.get("escalation_id"),
                contributor_ids=[int(c)
                                 for c in (task.get("contributor_ids") or [])],
                priority=str(task.get("priority") or PRIORITY_MEDIUM),
                start_date=task.get("start_date"),
                due_date=task.get("due_date"),
                critical_date=task.get("critical_date"),
                effort_days=task.get("effort_days"),
                critical=bool(task.get("critical")),
                next_step=str(task.get("next_step") or ""),
                # A plan picked up mid-flight opens in the state it described
                # rather than pretending every task begins at zero.
                status=str(task.get("status") or "NOT_STARTED"),
                weight=task.get("weight", 1),
                percent_complete=task.get("percent_complete", 0),
                blocked=bool(task.get("blocked")),
                blocker_reason=str(task.get("blocker_reason") or ""),
                source=source)
            task_ids[code.upper()] = int(row.id)

        for link in links_of(plan):
            before, after = _dep_key(link)
            service.create_dependency(
                session, principal, int(project.id),
                predecessor_type=kind_of(plan, before),
                predecessor_id=milestone_ids.get(before)
                or task_ids.get(before, 0),
                successor_type=kind_of(plan, after),
                successor_id=milestone_ids.get(after) or task_ids.get(after, 0),
                dependency_type=str(link.get("dependency_type")
                                    or DEP_FINISH_TO_START),
                lag_days=int(link.get("lag_days") or 0),
                notes=str(link.get("notes") or ""),
                source=source)

        draft.status = DRAFT_PUBLISHED
        draft.project_id = int(project.id)
        draft.code = project.code
        draft.name = project.name
        draft.step = STEP_REVIEW
        draft.version = int(draft.version or 1) + 1
        draft.updated_by = actor
        draft.updated_at = datetime.now(UTC)
        service.audit(session, "PLANNER_DRAFT_PUBLISHED", actor_id=actor,
                      project_id=int(project.id), source=source,
                      draft=draft.key, code=project.code,
                      milestones=len(milestone_ids), tasks=len(task_ids),
                      links=len(links_of(plan)))
        # The monitor re-evaluates a project whose shape changed; a project
        # that has just come into existence is the largest such change there
        # is, and the first Needs Attention list should not wait for a sweep.
        service.signal(session, int(project.id), "project_published")
        session.flush()
    return project


def _seat_everybody(session: Any, principal: Any, project: PlannerProject,
                    plan: dict[str, Any], source: str) -> None:
    """Put every person the plan names onto the project.

    A task owner who is not a participant cannot open the project they are
    being chased about. Access follows the role the plan gave them, and the
    plan naming somebody does not by itself make them an owner — §40.
    """
    governance = plan.get("governance") or {}
    creator = getattr(principal, "user_id", None)
    seats: dict[int, tuple[str, str]] = {}

    def seat(user_id: Any, role: str, access: str) -> None:
        found = _user(user_id)
        if found is None or (creator is not None and found == int(creator)):
            return
        # First seat wins: a sponsor who also owns a task stays the sponsor.
        seats.setdefault(found, (role, access))

    # The constants rather than the words: this seated escalation contacts as
    # "STAKEHOLDER", which is not one of the eight project roles, so
    # publishing ANY plan whose escalation contact was not already the
    # sponsor, manager or owner failed at the last step with a message about
    # role names. An escalation contact reads the project and is told when
    # something has been escalated to them; VIEWER is what that is.
    seat(governance.get("sponsor_id"), ROLE_SPONSOR, ACCESS_VIEWER)
    seat(governance.get("manager_id"), ROLE_MANAGER, ACCESS_EDITOR)
    seat(governance.get("owner_id"), ROLE_OWNER, ACCESS_EDITOR)
    seat(governance.get("escalation_id"), ROLE_VIEWER, ACCESS_VIEWER)
    for milestone in milestones_of(plan):
        seat(milestone.get("owner_id"), ROLE_WORKSTREAM_LEAD,
             ACCESS_CONTRIBUTOR)
        seat(milestone.get("escalation_id"), ROLE_VIEWER, ACCESS_VIEWER)
    for task in tasks_of(plan):
        seat(task.get("owner_id"), ROLE_CONTRIBUTOR, ACCESS_CONTRIBUTOR)
        seat(task.get("reviewer_id"), ROLE_REVIEWER, ACCESS_CONTRIBUTOR)
        seat(task.get("escalation_id"), ROLE_VIEWER, ACCESS_VIEWER)
        for contributor in task.get("contributor_ids") or []:
            seat(contributor, ROLE_CONTRIBUTOR, ACCESS_CONTRIBUTOR)

    for user_id, (role, access) in sorted(seats.items()):
        service.add_participant(session, principal, int(project.id),
                                user_id=user_id, project_role=role,
                                access=access, source=source)


__all__ = [
    "BLOCKER", "COMMANDS", "Completeness", "DRAFT_VERSION", "DraftError",
    "Note", "WARNING", "apply", "catalogue", "check", "create", "discard",
    "empty", "escalation_for", "item", "kind_of", "link_preview", "links_of",
    "list_for", "load", "milestone_code", "milestones_of", "preview",
    "previous_task", "publish", "save", "suggest_code", "task_code",
    "tasks_of", "to_dict",
]
