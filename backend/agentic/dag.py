"""
The agent task DAG. §16.

A plan is a set of bounded tasks and the order they may run in. Nothing here
executes anything; it decides what *can* run now, refuses a plan that cannot
terminate, and computes the layers the Trace draws.

Why a DAG and not a list
------------------------
§16's own example: Portfolio Risk and IFRS 9 may run at the same time, and
Validation & Assurance waits for both. Expressed as a list that is three steps
taking three times as long, and the dependency that actually matters —
"Assurance must not check a result that does not exist yet" — is implicit in the
ordering rather than stated. Expressed as a DAG, the parallelism is free and the
dependency is checked.

Termination
-----------
`validate()` refuses a plan with a cycle, a dangling dependency, a task for an
unregistered agent, a task using a tool that agent may not use, or more tasks
than the budget allows. That is where §73's "agent recursively delegates" stops:
a plan that delegates to itself does not fail at run time, it fails to be a
plan.

Layers
------
`layers()` is a topological grouping, not a topological sort. The difference is
the point: a sort gives one valid order, and a grouping gives every task that
could start now, which is what a parallel executor needs and what the Trace has
to draw.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task statuses
# ---------------------------------------------------------------------------

PENDING = "pending"
READY = "ready"
RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"
SKIPPED = "skipped"
CANCELLED = "cancelled"
BLOCKED = "blocked"
NEEDS_APPROVAL = "needs_approval"

FINISHED: frozenset[str] = frozenset(
    {COMPLETE, FAILED, SKIPPED, CANCELLED, BLOCKED})
SUCCEEDED: frozenset[str] = frozenset({COMPLETE})


class PlanRejected(ValueError):
    """A plan that cannot be executed safely. Raised before anything runs."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# ---------------------------------------------------------------------------
# A task
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """One bounded piece of work delegated to one specialist. §16's fields."""

    task_key: str
    agent_id: str
    purpose: str
    depends_on: tuple[str, ...] = ()
    tool: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    #: Which governed domains this task reads. Checked against the agent's
    #: permissions before the plan is accepted, not when the scan starts.
    domains: tuple[str, ...] = ()
    #: A task the run can complete without. A failed optional task degrades the
    #: answer honestly (§55); a failed required one stops it.
    optional: bool = False

    # -- filled in as it runs ---------------------------------------------
    layer: int = 0
    status: str = PENDING
    analysis_run_id: int | None = None
    result: dict[str, Any] = field(default_factory=dict)
    finding: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    validation_state: str = "not_required"
    validation: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    data_versions: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    error_category: str = ""
    error: str = ""
    approval_state: str = "not_required"
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int = 0

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

    @property
    def succeeded(self) -> bool:
        return self.status in SUCCEEDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "agent_id": self.agent_id,
            "purpose": self.purpose,
            "depends_on": list(self.depends_on),
            "layer": self.layer,
            "tool": self.tool,
            "parameters": dict(self.parameters),
            "inputs": dict(self.inputs),
            "domains": list(self.domains),
            "optional": self.optional,
            "status": self.status,
            "analysis_run_id": self.analysis_run_id,
            "finding": self.finding,
            "evidence": dict(self.evidence),
            "validation_state": self.validation_state,
            "validation": dict(self.validation),
            "tool_calls": list(self.tool_calls),
            "data_versions": dict(self.data_versions),
            "retry_count": self.retry_count,
            "error_category": self.error_category,
            "error": self.error,
            "approval_state": self.approval_state,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
        }


# ---------------------------------------------------------------------------
# A plan
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    """A set of tasks and the order they may run in."""

    objective: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    tasks: list[Task] = field(default_factory=list)
    #: Why this decomposition — shown in Trace, not written by a model.
    rationale: str = ""

    def __post_init__(self) -> None:
        self._index: dict[str, Task] = {}
        self.reindex()

    def reindex(self) -> None:
        self._index = {t.task_key: t for t in self.tasks}

    def task(self, key: str) -> Task | None:
        return self._index.get(key)

    def add(self, task: Task) -> Task:
        self.tasks.append(task)
        self._index[task.task_key] = task
        return task

    @property
    def agents(self) -> tuple[str, ...]:
        """Distinct specialists, in plan order."""
        seen: list[str] = []
        for task in self.tasks:
            if task.agent_id not in seen:
                seen.append(task.agent_id)
        return tuple(seen)

    @property
    def finished(self) -> bool:
        return all(t.finished for t in self.tasks)

    @property
    def failures(self) -> list[Task]:
        return [t for t in self.tasks if t.status == FAILED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "scope": dict(self.scope),
            "rationale": self.rationale,
            "agents": list(self.agents),
            "task_count": len(self.tasks),
            "layers": [[t.task_key for t in layer] for layer in self.layers()],
            "tasks": [t.to_dict() for t in self.tasks],
        }

    # -- structure ---------------------------------------------------------

    def layers(self) -> list[list[Task]]:
        """Tasks grouped by how deep they sit in the dependency graph.

        Everything in layer 0 may start immediately; everything in layer 1
        depends only on layer 0; and so on. A cycle produces a short grouping
        rather than an infinite loop — `validate()` is what refuses it.
        """
        depth: dict[str, int] = {}
        remaining = {t.task_key for t in self.tasks}
        found: list[list[Task]] = []

        while remaining:
            layer = [
                key for key in remaining
                if all(d in depth for d in (self._index[key].depends_on or ()))
            ]
            if not layer:
                # A cycle, or a dangling dependency. Stop rather than spin.
                break
            for key in layer:
                depth[key] = len(found)
                self._index[key].layer = len(found)
            found.append([self._index[k] for k in
                          sorted(layer, key=lambda k: self._order(k))])
            remaining -= set(layer)

        return found

    def _order(self, key: str) -> int:
        """Plan order, so a layer is drawn the way it was written rather than
        alphabetically."""
        for index, task in enumerate(self.tasks):
            if task.task_key == key:
                return index
        return 0

    def ready(self) -> list[Task]:
        """Every task that could start right now.

        A task is ready when it is pending and every dependency has SUCCEEDED.
        A dependency that failed does not make its dependants ready — it makes
        them blocked, which is `block_downstream`'s job and is a different
        thing from being skipped.
        """
        out: list[Task] = []
        for task in self.tasks:
            if task.status != PENDING:
                continue
            deps = [self._index.get(d) for d in (task.depends_on or ())]
            if all(d is not None and d.succeeded for d in deps):
                out.append(task)
        return out

    def block_downstream(self, key: str, *, reason: str) -> list[Task]:
        """Mark everything that depended on a failed task as blocked.

        Blocked, not failed. §55: a specialist that could not run leaves the
        tasks that needed it unable to run, and the honest report is "this part
        could not be done", not "this part failed" — nobody tried it.
        """
        blocked: list[Task] = []
        frontier = {key}
        while frontier:
            nxt: set[str] = set()
            for task in self.tasks:
                if task.status not in (PENDING, READY):
                    continue
                if set(task.depends_on or ()) & frontier:
                    task.status = BLOCKED
                    task.error = reason
                    task.error_category = "upstream_failed"
                    blocked.append(task)
                    nxt.add(task.task_key)
            frontier = nxt
        return blocked

    def cancel_pending(self, *, reason: str) -> list[Task]:
        out: list[Task] = []
        for task in self.tasks:
            if task.status in (PENDING, READY):
                task.status = CANCELLED
                task.error = reason
                out.append(task)
        return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(plan: Plan, *, max_tasks: int = 24,
             registry: Any = None) -> list[str]:
    """Everything wrong with this plan, before anything runs.

    Returns the reasons. An empty list means the plan is executable — not that
    it will succeed, but that it cannot loop, cannot reach a tool the agent was
    not granted, and cannot exceed the task budget.
    """
    from backend.agentic import registry as default_registry
    from backend.agentic import tools as tool_registry

    reg = registry or default_registry
    problems: list[str] = []

    if not plan.tasks:
        return ["The plan has no tasks."]

    if len(plan.tasks) > max_tasks:
        problems.append(
            f"The plan has {len(plan.tasks)} tasks; the budget allows "
            f"{max_tasks}.")

    keys = [t.task_key for t in plan.tasks]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        problems.append(
            f"Task keys must be unique; {', '.join(sorted(duplicates))} "
            f"appear more than once.")

    known = set(keys)
    for task in plan.tasks:
        for dependency in task.depends_on or ():
            if dependency not in known:
                problems.append(
                    f"Task '{task.task_key}' depends on '{dependency}', which "
                    f"is not in the plan.")
            if dependency == task.task_key:
                problems.append(f"Task '{task.task_key}' depends on itself.")

        agent = reg.agent(task.agent_id)
        if agent is None:
            problems.append(
                f"Task '{task.task_key}' is assigned to '{task.agent_id}', "
                f"which is not a registered agent.")
            continue

        if task.tool:
            if tool_registry.tool(task.tool) is None:
                problems.append(
                    f"Task '{task.task_key}' uses '{task.tool}', which is not "
                    f"a CreditProbe tool.")
            elif not agent.may_use(task.tool):
                problems.append(
                    f"{agent.business_name} may not use "
                    f"{tool_registry.require(task.tool).name} "
                    f"(task '{task.task_key}').")

        for domain in task.domains or ():
            if not agent.may_read(domain):
                problems.append(
                    f"{agent.business_name} may not read the {domain} domain "
                    f"(task '{task.task_key}').")

    # A cycle shows up as tasks that never reach a layer.
    placed = {t.task_key for layer in plan.layers() for t in layer}
    stranded = known - placed
    if stranded and not any("depends on" in p for p in problems):
        problems.append(
            f"These tasks can never run because they depend on each other: "
            f"{', '.join(sorted(stranded))}.")

    return problems


def require_valid(plan: Plan, *, max_tasks: int = 24,
                  registry: Any = None) -> None:
    problems = validate(plan, max_tasks=max_tasks, registry=registry)
    if problems:
        raise PlanRejected(problems)


def summarise(plan: Plan) -> str:
    """The completion line §11 asks for, built from the plan rather than
    written: "4 specialists · 6 analyses · 3 domains · all validations passed"."""
    from backend.agentic import registry as reg

    specialists = len(plan.agents)
    analyses = sum(1 for t in plan.tasks if t.analysis_run_id)
    domains = {d for t in plan.tasks for d in (t.domains or ())}
    checked = [t for t in plan.tasks if t.validation_state != "not_required"]
    passed = all(t.validation_state == "passed" for t in checked)

    parts = [_plural(specialists, "specialist")]
    if analyses:
        parts.append(_plural(analyses, "analysis", "analyses"))
    if domains:
        parts.append(_plural(len(domains), "domain"))
    if checked:
        parts.append("all checks passed" if passed
                     else f"{sum(1 for t in checked if t.validation_state != 'passed')} "
                          f"check(s) did not pass")
    _ = reg  # kept for symmetry with the caller's registry override
    return " · ".join(parts)


def _plural(count: int, word: str, plural: str = "") -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def as_tasks(rows: Iterable[Any]) -> list[Task]:
    """Rebuild tasks from stored rows, for reading a run back."""
    out: list[Task] = []
    for row in rows:
        out.append(Task(
            task_key=str(getattr(row, "task_key", "")),
            agent_id=str(getattr(row, "agent_id", "")),
            purpose=str(getattr(row, "purpose", "") or ""),
            depends_on=tuple(getattr(row, "depends_on", ()) or ()),
            tool=str(getattr(row, "tool", "") or ""),
            parameters=dict(getattr(row, "parameters", {}) or {}),
            inputs=dict(getattr(row, "inputs", {}) or {}),
            layer=int(getattr(row, "layer", 0) or 0),
            status=str(getattr(row, "status", PENDING)),
            analysis_run_id=getattr(row, "analysis_run_id", None),
            result=dict(getattr(row, "result", {}) or {}),
            finding=str(getattr(row, "finding", "") or ""),
            evidence=dict(getattr(row, "evidence", {}) or {}),
            validation_state=str(getattr(row, "validation_state",
                                         "not_required")),
            validation=dict(getattr(row, "validation", {}) or {}),
            tool_calls=list(getattr(row, "tool_calls", []) or []),
            data_versions=dict(getattr(row, "data_versions", {}) or {}),
            retry_count=int(getattr(row, "retry_count", 0) or 0),
            error_category=str(getattr(row, "error_category", "") or ""),
            error=str(getattr(row, "error", "") or ""),
            approval_state=str(getattr(row, "approval_state", "not_required")),
            duration_ms=int(getattr(row, "duration_ms", 0) or 0),
        ))
    return out


__all__ = [
    "BLOCKED",
    "CANCELLED",
    "COMPLETE",
    "FAILED",
    "FINISHED",
    "NEEDS_APPROVAL",
    "PENDING",
    "READY",
    "RUNNING",
    "SKIPPED",
    "SUCCEEDED",
    "Plan",
    "PlanRejected",
    "Task",
    "as_tasks",
    "require_valid",
    "summarise",
    "validate",
]
