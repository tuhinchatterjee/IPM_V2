"""What the person filling the form is told: where they are, and what is next.

Two functions, and nothing else.

`progress` answers "how far through this am I?" — eight sections, each with a
state, a count of what it still wants, and a one-line summary of what it
holds. Derived entirely from the draft: there is no stored progress, no
counter incremented on save and nothing to go stale. Delete a sponsor and
governance stops being complete in the same breath.

`guidance` answers "what should I do now?" — what is done, what is missing,
what would stop a publish, and the single next step, with the field to go to.
It is arithmetic over the plan, like everything else the agent says. It is
not a chatbot: it cannot be asked a question, so it can never answer one
wrongly, and every sentence it produces names the thing it read.

Both take the plan, and optionally the names of the people it mentions, so
they stay pure functions of the document. Neither touches the database.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.models.planner import (
    STEP_AGENTIC,
    STEP_DEPENDENCIES,
    STEP_GOVERNANCE,
    STEP_MILESTONES,
    STEP_OVERVIEW,
    STEP_REVIEW,
    STEP_TASKS,
)
from backend.planner import draft as dr
from backend.planner import policy as pol

#: The eight sections of the creation form, in the order it asks them. Seven
#: of them are steps the draft records; publish is the eighth and is not a
#: place a draft rests, so it has no stored step of its own.
STEP_PUBLISH = "PUBLISH"

#: Every state a section can be in. Four, because three cannot separate
#: "there is nothing here yet" from "what is here is wrong".
NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
NEEDS_ATTENTION = "needs_attention"
COMPLETE = "complete"

STATE_LABELS = {
    NOT_STARTED: "Not started",
    IN_PROGRESS: "In progress",
    NEEDS_ATTENTION: "Needs attention",
    COMPLETE: "Complete",
}

#: section key -> (step, number, title, the completeness scopes it owns)
SECTIONS: tuple[tuple[str, str, int, str, tuple[str, ...]], ...] = (
    ("overview", STEP_OVERVIEW, 1, "Overview", ("overview",)),
    ("governance", STEP_GOVERNANCE, 2, "People and governance",
     ("governance",)),
    ("agentic", STEP_AGENTIC, 3, "Agentic AI policy", ("agentic",)),
    ("milestones", STEP_MILESTONES, 4, "Major milestones",
     ("milestones", "milestone")),
    ("tasks", STEP_TASKS, 5, "Tasks", ("task",)),
    ("dependencies", STEP_DEPENDENCIES, 6, "Dependencies", ("link",)),
    ("review", STEP_REVIEW, 7, "Review", ()),
    ("publish", STEP_PUBLISH, 8, "Publish", ()),
)

STEP_OF_SECTION = {key: step for key, step, _n, _t, _s in SECTIONS}
SECTION_OF_STEP = {step: key for key, step, _n, _t, _s in SECTIONS}
NUMBER_OF_SECTION = {key: number for key, _st, number, _t, _s in SECTIONS}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _name_of(names: dict[int, str] | None, user_id: Any) -> str:
    if not user_id:
        return ""
    if names and int(user_id) in names:
        return names[int(user_id)]
    return f"#{int(user_id)}"


def _pretty(day: date | None) -> str:
    return day.strftime("%-d %b %Y") if day else ""


# ------------------------------------------------------------------ wanted


def _wanted(plan: dict[str, Any]) -> dict[str, list[tuple[str, bool, str]]]:
    """What each section asks for, and whether it has it.

    (label, satisfied, field) per item. This is the business meaning of
    "complete" — not "the person pressed Next", which is a claim about the
    person rather than about the plan.
    """
    overview = plan.get("overview") or {}
    governance = plan.get("governance") or {}
    milestones = dr.milestones_of(plan)
    tasks = dr.tasks_of(plan)
    links = dr.links_of(plan)

    def named(key: str) -> bool:
        return bool(governance.get(key))

    milestones_ok = bool(milestones) and all(
        _text(m.get("name")) and m.get("owner_id") and m.get("target_date")
        for m in milestones)
    every_milestone_worked = bool(milestones) and all(
        dr.tasks_of(plan, str(m.get("code") or "")) for m in milestones)
    tasks_ok = bool(tasks) and all(
        _text(t.get("title")) and t.get("owner_id") and t.get("due_date")
        for t in tasks)

    return {
        "overview": [
            ("A name", bool(_text(overview.get("name"))), "overview.name"),
            ("A project code", bool(_text(overview.get("code"))),
             "overview.code"),
            ("What it is for", bool(_text(overview.get("description"))),
             "overview.description"),
            ("What finished looks like", bool(_text(overview.get("objective"))),
             "overview.objective"),
        ],
        "governance": [
            ("A sponsor", named("sponsor_id"), "governance.sponsor_id"),
            ("A project manager", named("manager_id"),
             "governance.manager_id"),
            ("An owner", named("owner_id"), "governance.owner_id"),
            ("An escalation contact", named("escalation_id"),
             "governance.escalation_id"),
            ("A start date", bool(_day(governance.get("start_date"))),
             "governance.start_date"),
            ("A target completion date",
             bool(_day(governance.get("target_end_date"))),
             "governance.target_end_date"),
        ],
        "agentic": [
            ("A monitoring policy",
             bool(_text((plan.get("agentic") or {}).get("mode"))),
             "agentic.mode"),
        ],
        "milestones": [
            ("At least one milestone", bool(milestones), "milestones.add"),
            ("An owner and a date on every milestone", milestones_ok,
             "milestones.add"),
        ],
        "tasks": [
            ("Work under every milestone", every_milestone_worked,
             "tasks.add"),
            ("An owner and a due date on every task", tasks_ok, "tasks.add"),
        ],
        "dependencies": [
            ("What waits for what", bool(links), "dependencies.add"),
        ],
    }


def _summary(plan: dict[str, Any], key: str,
             names: dict[int, str] | None) -> str:
    """One line a completed section collapses to. §12."""
    overview = plan.get("overview") or {}
    governance = plan.get("governance") or {}
    if key == "overview":
        name = _text(overview.get("name"))
        code = _text(overview.get("code"))
        if name and code:
            return f"{name} ({code})"
        return name or code
    if key == "governance":
        parts = []
        for field_, label in (("sponsor_id", "Sponsor"),
                              ("manager_id", "Manager")):
            who = _name_of(names, governance.get(field_))
            if who:
                parts.append(f"{label} {who}")
        start = _pretty(_day(governance.get("start_date")))
        end = _pretty(_day(governance.get("target_end_date")))
        if start and end:
            parts.append(f"{start} → {end}")
        return " · ".join(parts)
    if key == "agentic":
        agentic = plan.get("agentic") or {}
        try:
            resolved = pol.resolve(agentic.get("mode", ""),
                                   agentic.get("policy"))
        except pol.PolicyError as exc:
            return str(exc)
        return resolved.label
    if key == "milestones":
        count = len(dr.milestones_of(plan))
        if not count:
            return ""
        return f"{count} milestone{'' if count == 1 else 's'}"
    if key == "tasks":
        count = len(dr.tasks_of(plan))
        if not count:
            return ""
        return f"{count} task{'' if count == 1 else 's'}"
    if key == "review":
        found = dr.check(plan)
        if found.publishable:
            return "Ready to publish"
        left = len(found.blockers)
        return (f"{left} required item{'' if left == 1 else 's'} remain"
                f"{'s' if left == 1 else ''}")
    if key == "dependencies":
        count = len(dr.links_of(plan))
        if count:
            return f"{count} dependenc{'y' if count == 1 else 'ies'}"
        if len(dr.tasks_of(plan)) < 2:
            return ""
        return "Nothing depends on anything else"
    return ""


def _touched(plan: dict[str, Any], key: str) -> bool:
    """Has anybody put anything into this section at all?"""
    if key == "overview":
        return any(_text(v) for v in (plan.get("overview") or {}).values())
    if key == "governance":
        governance = plan.get("governance") or {}
        return any(governance.get(k) for k in
                   ("sponsor_id", "manager_id", "owner_id", "escalation_id",
                    "start_date", "target_end_date"))
    if key == "agentic":
        return True  # a mode is always set; the default is a decision too
    if key == "milestones":
        return bool(dr.milestones_of(plan))
    if key == "tasks":
        return bool(dr.tasks_of(plan))
    if key == "dependencies":
        # Only started once something has been linked. With no links the
        # question "what waits for what?" has not been answered — and with
        # fewer than two tasks it has not been asked.
        return bool(dr.links_of(plan))
    return False


# ---------------------------------------------------------------- progress


def progress(plan: dict[str, Any], *, names: dict[int, str] | None = None,
             status: str = "") -> dict[str, Any]:
    """The eight sections, each with its state, counts and summary. §4, §5."""
    found = dr.check(plan)
    wanted = _wanted(plan)
    published = str(status or "").upper() == "PUBLISHED"

    by_scope: dict[str, list[dr.Note]] = {}
    for note in found.notes:
        by_scope.setdefault(note.scope, []).append(note)

    sections: list[dict[str, Any]] = []
    for key, step, number, title, scopes in SECTIONS:
        notes = [n for scope in scopes for n in by_scope.get(scope, [])]
        blockers = [n for n in notes if n.level == dr.BLOCKER]
        warnings = [n for n in notes if n.level == dr.WARNING]
        items = wanted.get(key, [])
        done = sum(1 for _label, ok, _field in items if ok)

        if key == "review":
            state = (COMPLETE if found.publishable
                     else NEEDS_ATTENTION if not _all_untouched(plan)
                     else NOT_STARTED)
            done, total = (1, 1) if found.publishable else (0, 1)
        elif key == "publish":
            state = COMPLETE if published else NOT_STARTED
            done, total = (1, 1) if published else (0, 1)
        else:
            total = len(items)
            if not _touched(plan, key):
                # Untouched comes first. A section nobody has opened is not
                # in trouble; saying it needs attention on a blank form makes
                # every section shout on the first screen and the word stops
                # meaning anything.
                state = NOT_STARTED
            elif blockers:
                state = NEEDS_ATTENTION
            elif done == total and total:
                state = COMPLETE
            else:
                state = IN_PROGRESS

        sections.append({
            "key": key, "step": step, "number": number, "title": title,
            "state": state, "label": STATE_LABELS[state],
            "done": done, "total": total,
            "blockers": len(blockers), "warnings": len(warnings),
            "summary": _summary(plan, key, names),
            "field": _first_gap(items),
        })

    complete = sum(1 for s in sections if s["state"] == COMPLETE)
    required = len(found.blockers)
    return {
        "sections": sections,
        "complete": complete,
        "total": len(sections),
        "sentence": f"{complete} of {len(sections)} sections complete",
        "publishable": found.publishable,
        "required_remaining": required,
        "publish_message": _publish_message(found.publishable, required,
                                            published),
    }


def _all_untouched(plan: dict[str, Any]) -> bool:
    return not any(_touched(plan, key) for key in
                   ("overview", "governance", "milestones", "tasks"))


def _first_gap(items: list[tuple[str, bool, str]]) -> str:
    for _label, ok, field_ in items:
        if not ok:
            return field_
    return ""


def _publish_message(publishable: bool, required: int,
                     published: bool) -> str:
    """§15. Why the button is not available, in the number of things left."""
    if published:
        return "Published."
    if publishable:
        return "Everything required is in place."
    return (f"Publish unavailable — {required} required item"
            f"{'' if required == 1 else 's'} remain"
            f"{'s' if required == 1 else ''}.")


# ---------------------------------------------------------------- guidance


#: What the assistant offers to do on each step, beyond filling the fields in
#: front of the person. Each one is a control the form already has; the
#: assistant points at it rather than doing anything of its own.
def _actions(plan: dict[str, Any], key: str,
             found: dr.Completeness) -> list[dict[str, Any]]:
    governance = plan.get("governance") or {}
    actions: list[dict[str, Any]] = []
    if key == "governance":
        if not governance.get("sponsor_id"):
            actions.append({"label": "Assign sponsor",
                            "field": "governance.sponsor_id"})
        if not governance.get("escalation_id"):
            actions.append({"label": "Set escalation contact",
                            "field": "governance.escalation_id"})
    if key == "milestones":
        actions.append({"label": "Add milestone", "field": "milestones.add"})
    if key == "tasks":
        empty = [str(m.get("code") or "") for m in dr.milestones_of(plan)
                 if not dr.tasks_of(plan, str(m.get("code") or ""))]
        if empty:
            actions.append({"label": f"Add work to {empty[0]}",
                            "field": f"tasks.{empty[0]}.add"})
    if key == "dependencies":
        loose = unlinked_tasks(plan)
        if loose:
            actions.append({"label": f"Show {len(loose)} unlinked task"
                                     f"{'' if len(loose) == 1 else 's'}",
                            "field": "dependencies.unlinked",
                            "codes": loose})
    actions.append({"label": "Check readiness", "field": "readiness"})
    return actions


def unlinked_tasks(plan: dict[str, Any]) -> list[str]:
    """Tasks no dependency mentions, in plan order.

    Not a fault — most tasks in most plans are independent — but it is the
    question step six exists to ask, and a person cannot answer it without
    being shown which ones they are.
    """
    linked: set[str] = set()
    for link in dr.links_of(plan):
        linked.add(str(link.get("predecessor") or "").upper())
        linked.add(str(link.get("successor") or "").upper())
    return [str(task.get("code") or "") for task in dr.tasks_of(plan)
            if str(task.get("code") or "").upper() not in linked]


def _conflicts(found: dr.Completeness) -> list[dict[str, Any]]:
    """Dates that contradict each other, and owners nobody named.

    Drawn from the completeness notes rather than recomputed, so the panel and
    the assistant can never disagree about what is wrong.
    """
    out: list[dict[str, Any]] = []
    for note in found.notes:
        message = note.message
        if "before it starts" in message or "after the project's target" in \
                message or "after its milestone" in message or \
                "would finish on" in message or "loop" in message or \
                "overlap" in message.lower():
            out.append({"message": message, "field": note.field,
                        "code": note.code, "level": note.level,
                        "step": _step_for(note)})
    return out


def _step_for(note: dr.Note) -> str:
    """Which step of the form a note belongs to."""
    scope = note.scope
    if scope in ("overview",):
        return STEP_OVERVIEW
    if scope in ("governance",):
        return STEP_GOVERNANCE
    if scope in ("agentic",):
        return STEP_AGENTIC
    if scope in ("milestones", "milestone"):
        return STEP_MILESTONES
    if scope in ("task",):
        return STEP_TASKS
    if scope in ("link",):
        return STEP_DEPENDENCIES
    return STEP_REVIEW


def guidance(plan: dict[str, Any], *, names: dict[int, str] | None = None,
             step: str = "", status: str = "") -> dict[str, Any]:
    """The setup assistant's whole output. §6, §7, §8.

    Everything here is derived. Nothing is generated, nothing is guessed, and
    there is no free-text field to type into: the assistant reports on the
    plan, and the plan is the only thing it can see.
    """
    found = dr.check(plan)
    bars = progress(plan, names=names, status=status)
    wanted = _wanted(plan)
    here = SECTION_OF_STEP.get(str(step or "").upper(), "overview")

    complete = [
        {"section": section["title"], "summary": section["summary"],
         "step": section["step"]}
        for section in bars["sections"]
        if section["state"] == COMPLETE and section["summary"]
    ]

    missing: list[dict[str, Any]] = []
    for note in found.blockers:
        missing.append({"message": note.message, "fix": note.fix,
                        "field": note.field, "code": note.code,
                        "step": _step_for(note), "level": note.level})
    recommended = [
        {"message": note.message, "fix": note.fix, "field": note.field,
         "code": note.code, "step": _step_for(note), "level": note.level}
        for note in found.warnings]

    return {
        "here": here,
        "headline": _headline(bars, found),
        "complete": complete,
        "missing": missing,
        "recommended": recommended,
        "conflicts": _conflicts(found),
        "next": _next_step(plan, bars, found, wanted),
        "actions": _actions(plan, here, found),
        "readiness": {
            "publishable": bars["publishable"],
            "required_remaining": bars["required_remaining"],
            "message": bars["publish_message"],
        },
    }


def _headline(bars: dict[str, Any], found: dr.Completeness) -> str:
    if bars["publishable"]:
        return ("Everything required is in place. "
                + bars["sentence"] + ".")
    required = bars["required_remaining"]
    return (f"{bars['sentence']}. {required} required item"
            f"{'' if required == 1 else 's'} still to go.")


def _next_step(plan: dict[str, Any], bars: dict[str, Any],
               found: dr.Completeness,
               wanted: dict[str, list[tuple[str, bool, str]]]
               ) -> dict[str, Any]:
    """The one thing to do now, and where it is. §8.

    The first required thing missing, in the order the form asks. Required
    before recommended, and earlier steps before later ones, because a person
    told to write a task description while the project has no sponsor is
    being helped with the wrong thing.
    """
    for note in found.blockers:
        return {"step": _step_for(note), "field": note.field,
                "title": note.message,
                "why": note.fix or "This stops the project being published.",
                "required": True}
    for key, _step, _number, title, _scopes in SECTIONS:
        for label, ok, field_ in wanted.get(key, []):
            if not ok:
                return {"step": STEP_OF_SECTION[key], "field": field_,
                        "title": f"{label.lower()} — {title}",
                        "why": "Not required, but the plan reads better "
                               "with it.",
                        "required": False}
    for note in found.warnings:
        return {"step": _step_for(note), "field": note.field,
                "title": note.message,
                "why": note.fix or "Worth fixing before you publish.",
                "required": False}
    return {"step": STEP_PUBLISH, "field": "publish",
            "title": "Publish the project",
            "why": "Everything required is in place.", "required": False}


__all__ = [
    "COMPLETE", "IN_PROGRESS", "NEEDS_ATTENTION", "NOT_STARTED",
    "NUMBER_OF_SECTION", "SECTIONS", "SECTION_OF_STEP", "STATE_LABELS",
    "STEP_OF_SECTION", "STEP_PUBLISH", "guidance", "progress",
    "unlinked_tasks",
]
