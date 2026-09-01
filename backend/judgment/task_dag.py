"""
An investigation as a bounded DAG, and when it may say it is finished.
§92, §93.

    §92: "A blueprint compiles to a bounded DAG. … No duplicate analyses
          unless a challenge method deliberately differs."
    §93: "No polished answer from a failed/incomplete investigation."

Why a DAG rather than a list of steps
--------------------------------------
Because the dependencies are the analysis. A breadth verdict computed before
the driver decomposition has run is a breadth verdict over nothing; a synthesis
that ran before the challenge pass has synthesised an unchallenged conclusion.
A list can be executed in the wrong order and look identical afterwards. A DAG
cannot: `ready()` will not hand out a task whose inputs do not exist.

Bounded, because an investigation that can add tasks while running can run
forever, and the version that runs forever in front of a client is the one
that matters. The DAG is compiled from the blueprint before anything executes,
and it does not grow.

Why duplicates are refused
---------------------------
Two identical analyses cost twice and, worse, can disagree — same question,
same data, two runs, two numbers, and nothing on screen saying which is the
answer. The one exception §92 allows is a challenge method that DELIBERATELY
differs: the challenge pass exists to compute the same thing another way, and
refusing that would refuse the control. So the exception is explicit and
carries the difference in the task itself, rather than being a flag anybody
can set.

§93 is the honest-failure rule
-------------------------------
Nine conditions, and the sentence under them is the point: no polished answer
from a failed investigation. The tempting behaviour is to show what did work
and quietly omit what did not, and it is tempting because the partial answer
is often genuinely useful. It is still an answer whose gaps are invisible, and
a credit officer cannot act on an analysis whose missing half they cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DAG_VERSION = "1.0.0"

# ------------------------------------------------------- §92's task types
SCOPE = "SCOPE"
DATA_AVAILABILITY = "DATA_AVAILABILITY"
ANALYSIS = "ANALYSIS"
DRIVER = "DRIVER"
CONTRIBUTION = "CONTRIBUTION"
BREADTH = "BREADTH"
PERSISTENCE = "PERSISTENCE"
CONTRADICTION = "CONTRADICTION"
CHALLENGE = "CHALLENGE"
VALIDATION = "VALIDATION"
SYNTHESIS = "SYNTHESIS"
VISUALIZATION = "VISUALIZATION"

TASK_TYPES: tuple[str, ...] = (
    SCOPE, DATA_AVAILABILITY, ANALYSIS, DRIVER, CONTRIBUTION, BREADTH,
    PERSISTENCE, CONTRADICTION, CHALLENGE, VALIDATION, SYNTHESIS,
    VISUALIZATION,
)

#: What each type is for. Listed because a DAG whose node types nobody can
#: define gets nodes added to it by whoever is writing a blueprint that week.
TYPE_MEANS: dict[str, str] = {
    SCOPE: "Establish the population, period and grain everything else is "
           "computed over.",
    DATA_AVAILABILITY: "Establish what exists before planning around it.",
    ANALYSIS: "Run a governed method and produce a result.",
    DRIVER: "Decompose a movement into contributions that reconcile.",
    CONTRIBUTION: "Attribute one entity's share of a movement.",
    BREADTH: "Decide broad or concentrated, from measures.",
    PERSISTENCE: "Decide sustained or a spike, from history.",
    CONTRADICTION: "Detect and diagnose signals that disagree.",
    CHALLENGE: "Attack the conclusion before anybody else does.",
    VALIDATION: "Check the invariants the result must satisfy.",
    SYNTHESIS: "Say what it all means, from the facts and nothing else.",
    VISUALIZATION: "Choose and check the picture.",
}

#: Types that structurally depend on something else having produced a result.
#: A DAG that permitted a SYNTHESIS with no inputs would permit an
#: investigation that concluded before it analysed.
NEEDS_INPUT: frozenset[str] = frozenset({
    DRIVER, CONTRIBUTION, BREADTH, PERSISTENCE, CONTRADICTION, CHALLENGE,
    VALIDATION, SYNTHESIS, VISUALIZATION})

# ------------------------------------------------------------ task status
PENDING = "PENDING"
READY = "READY"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
#: The task could not run because what it needed does not exist. Distinct
#: from FAILED: a missing covenant dataset is not a defect in CreditProbe,
#: and §93 lets an objective be "explicitly unavailable" for exactly this.
UNAVAILABLE = "UNAVAILABLE"
#: Not run because a dependency failed. Never reported as a pass.
BLOCKED = "BLOCKED"
SKIPPED = "SKIPPED"

STATUSES: tuple[str, ...] = (PENDING, READY, RUNNING, COMPLETED, FAILED,
                             UNAVAILABLE, BLOCKED, SKIPPED)

#: Statuses that let downstream work proceed.
SATISFIED: frozenset[str] = frozenset({COMPLETED, UNAVAILABLE})


@dataclass
class Task:
    """One node. §92's persisted fields, all of them."""

    task_id: str
    task_type: str = ANALYSIS
    objective: str = ""
    #: The governed method or tool this runs. Named, never a model id.
    method: str = ""
    dependencies: list[str] = field(default_factory=list)
    status: str = PENDING
    result: dict[str, Any] | None = None
    fact_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    duration_ms: int = 0
    budget_ms: int = 0
    validation: str = ""
    #: Why this task is not a duplicate of another with the same method. Only
    #: a CHALLENGE task may set it, and only with a stated difference.
    differs_because: str = ""
    note: str = ""

    @property
    def satisfied(self) -> bool:
        return self.status in SATISFIED

    @property
    def over_budget(self) -> bool:
        return bool(self.budget_ms) and self.duration_ms > self.budget_ms

    def fingerprint(self) -> str:
        """What makes two tasks the same analysis.

        The method and the objective, and deliberately NOT the task type. A
        CHALLENGE task that repeats an ANALYSIS is the exact case §92's rule
        is about — including the type here would give the two different
        fingerprints, and the one duplicate the rule exists to govern would
        be the one it never saw.
        """
        return f"{self.method}:{self.objective}".lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "task_type": self.task_type,
            "type_means": TYPE_MEANS.get(self.task_type, ""),
            "objective": self.objective, "method": self.method,
            "dependencies": list(self.dependencies), "status": self.status,
            "result": self.result, "fact_ids": list(self.fact_ids),
            "observation_ids": list(self.observation_ids),
            "duration_ms": self.duration_ms, "budget_ms": self.budget_ms,
            "over_budget": self.over_budget, "validation": self.validation,
            "differs_because": self.differs_because, "note": self.note,
        }


class Duplicate(Exception):
    """Two tasks running the same analysis.

    Refused rather than deduplicated, because a silently dropped task leaves
    a blueprint that looks like it covered something it did not — and because
    the cost of the duplicate is the smaller half of the problem. Two runs of
    the same analysis can DISAGREE, and then two numbers are on screen with
    nothing saying which is the answer.
    """


class Cycle(Exception):
    """A dependency loop. A DAG with a cycle is not a DAG and cannot finish."""


class UnknownDependency(Exception):
    """A task depending on something the DAG does not contain."""


@dataclass
class Dag:
    """A compiled investigation. Bounded: no task is added after compile."""

    investigation_id: str = ""
    blueprint_id: str = ""
    tasks: list[Task] = field(default_factory=list)
    sealed: bool = False

    def get(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.task_id == task_id), None)

    def add(self, task: Task) -> Task:
        """One task, checked against everything already here.

        Refuses after sealing, because "bounded" that a caller can extend at
        runtime is not bounded.
        """
        if self.sealed:
            raise ValueError(
                "the DAG is sealed; §92 compiles a BOUNDED graph and an "
                "investigation that can add work while running can run "
                "forever")
        if task.task_type not in TASK_TYPES:
            raise KeyError(f"{task.task_type!r} is not one of §92's task types")
        if self.get(task.task_id):
            raise Duplicate(f"{task.task_id!r} is already in this DAG")

        same = [t for t in self.tasks
                if t.fingerprint() == task.fingerprint()]
        if same:
            # §92's one exception, and it is narrow on purpose.
            if not (task.task_type == CHALLENGE and task.differs_because):
                raise Duplicate(
                    f"{task.task_id!r} runs the same analysis as "
                    f"{same[0].task_id!r}; only a challenge method that "
                    "deliberately differs may repeat one, and it must say how")

        unknown = [d for d in task.dependencies if not self.get(d)]
        if unknown:
            raise UnknownDependency(
                f"{task.task_id!r} depends on {unknown[0]!r}, which is not in "
                "this DAG")
        if task.task_type in NEEDS_INPUT and not task.dependencies:
            raise UnknownDependency(
                f"a {task.task_type} task has nothing to work from; "
                f"{task.task_id!r} must depend on the task that produces it")

        self.tasks.append(task)
        return task

    def seal(self) -> Dag:
        """Close the graph and check it is one."""
        self._check_acyclic()
        self.sealed = True
        for task in self.tasks:
            if not task.dependencies:
                task.status = READY
        return self

    def _check_acyclic(self) -> None:
        colour: dict[str, int] = {}

        def visit(task_id: str, path: list[str]) -> None:
            state = colour.get(task_id, 0)
            if state == 1:
                loop = " -> ".join([*path, task_id])
                raise Cycle(f"dependency loop: {loop}")
            if state == 2:
                return
            colour[task_id] = 1
            node = self.get(task_id)
            for dependency in (node.dependencies if node else []):
                visit(dependency, [*path, task_id])
            colour[task_id] = 2

        for task in self.tasks:
            visit(task.task_id, [])

    def ready(self) -> list[Task]:
        """Tasks whose dependencies are all satisfied.

        The whole reason this is a graph: a breadth verdict computed before
        the decomposition ran is a breadth verdict over nothing, and a list of
        steps executed in the wrong order looks identical afterwards.
        """
        available: list[Task] = []
        for task in self.tasks:
            if task.status not in (PENDING, READY):
                continue
            inputs = [self.get(d) for d in task.dependencies]
            if all(i is not None and i.satisfied for i in inputs):
                task.status = READY
                available.append(task)
        return available

    def record(self, task_id: str, status: str, *,
               result: dict[str, Any] | None = None,
               facts: list[str] | None = None,
               observations: list[str] | None = None,
               duration_ms: int = 0, validation: str = "",
               note: str = "") -> Task:
        """One task's outcome, and the blocking it causes.

        A failed task blocks everything downstream rather than letting it run
        on missing input, because the alternative is a synthesis over a hole.
        """
        task = self.get(task_id)
        if task is None:
            raise KeyError(f"{task_id!r} is not in this DAG")
        if status not in STATUSES:
            raise ValueError(f"{status!r} is not a task status")
        if status == UNAVAILABLE and not note:
            raise ValueError(
                "an unavailable task must say what was missing; §93 lets an "
                "objective be explicitly unavailable, and 'explicitly' is the "
                "whole of it")
        task.status = status
        task.result = result
        task.fact_ids = list(facts or [])
        task.observation_ids = list(observations or [])
        task.duration_ms = duration_ms
        task.validation = validation
        task.note = note
        if status == FAILED:
            self._block_downstream(task_id)
        return task

    def _block_downstream(self, task_id: str) -> None:
        changed = True
        blocked = {task_id}
        while changed:
            changed = False
            for task in self.tasks:
                if task.status in (COMPLETED, FAILED, UNAVAILABLE):
                    continue
                if any(d in blocked for d in task.dependencies):
                    if task.status != BLOCKED:
                        task.status = BLOCKED
                        changed = True
                    blocked.add(task.task_id)

    def by_status(self, status: str) -> list[Task]:
        return [t for t in self.tasks if t.status == status]

    def by_type(self, task_type: str) -> list[Task]:
        return [t for t in self.tasks if t.task_type == task_type]

    @property
    def failed(self) -> list[Task]:
        return self.by_status(FAILED)

    @property
    def outstanding(self) -> list[Task]:
        return [t for t in self.tasks if t.status not in
                (COMPLETED, UNAVAILABLE, SKIPPED)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": DAG_VERSION,
            "investigation_id": self.investigation_id,
            "blueprint_id": self.blueprint_id, "sealed": self.sealed,
            "tasks": [t.to_dict() for t in self.tasks],
            "counts": {s: len(self.by_status(s)) for s in STATUSES
                       if self.by_status(s)},
            "outstanding": [t.task_id for t in self.outstanding],
            "total_duration_ms": sum(t.duration_ms for t in self.tasks),
            "over_budget": [t.task_id for t in self.tasks if t.over_budget],
        }


# ---------------------------------------------------------------------------
# §93 — when an investigation may say it is finished
# ---------------------------------------------------------------------------

OBJECTIVES = "every_mandatory_objective_complete_or_unavailable"
HYPOTHESES = "hypothesis_statuses_recorded"
CHALLENGED = "challenge_pass_ran"
VALIDATED = "validations_passed"
FACTS = "result_facts_exist"
GROUNDED = "interpretation_is_grounded"
VISUAL = "visualization_passed_the_critic"
LIMITATIONS = "limitations_present"
TRACE = "trace_is_consistent"

CONDITIONS: tuple[str, ...] = (OBJECTIVES, HYPOTHESES, CHALLENGED, VALIDATED,
                               FACTS, GROUNDED, VISUAL, LIMITATIONS, TRACE)

CONDITION_ASKS: dict[str, str] = {
    OBJECTIVES: "Is every mandatory objective complete, or explicitly "
                "unavailable with a stated reason?",
    HYPOTHESES: "Does every hypothesis have a recorded status?",
    CHALLENGED: "Did the challenge pass run?",
    VALIDATED: "Did every validation pass?",
    FACTS: "Do registered validated facts exist for what the answer says?",
    GROUNDED: "Does every figure in the narrative trace to a fact?",
    VISUAL: "Did the chart pass the Visual Critic, or fall back to a table?",
    LIMITATIONS: "Are the limitations stated?",
    TRACE: "Is the Trace consistent with what actually ran?",
}


@dataclass
class Completion:
    """Whether an investigation may present a polished answer. §93."""

    met: dict[str, bool] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def unmet(self) -> list[str]:
        return [c for c in CONDITIONS if not self.met.get(c)]

    @property
    def complete(self) -> bool:
        return not self.unmet

    def sentence(self) -> str:
        """What the reader is told when it is not complete.

        Names what is missing rather than saying the investigation failed,
        because "could not check covenants — the dataset has no data after
        Q4 2025" is useful and "investigation incomplete" is not.
        """
        if self.complete:
            return "The investigation is complete and may be presented."
        missing = "; ".join(
            self.reasons.get(c) or CONDITION_ASKS[c] for c in self.unmet)
        return (f"This investigation is not complete, so what it did produce "
                f"is shown as findings rather than as an answer: {missing}")

    def to_dict(self) -> dict[str, Any]:
        return {"version": DAG_VERSION, "complete": self.complete,
                "conditions": [{"id": c, "asks": CONDITION_ASKS[c],
                                "met": bool(self.met.get(c)),
                                "reason": self.reasons.get(c, "")}
                               for c in CONDITIONS],
                "unmet": self.unmet, "sentence": self.sentence()}


def completion(dag: Dag, *, hypotheses_recorded: bool = False,
               validations_passed: bool = False, facts: int = 0,
               grounded: bool = False, visual_approved: bool = False,
               limitations: int = 0,
               trace_consistent: bool = False) -> Completion:
    """§93's nine conditions, checked rather than asserted.

    Everything that can be read off the DAG is read off the DAG; the rest is
    passed in from the engine that owns it. Nothing defaults to true — an
    unchecked condition is an unmet one, which is the same rule the assurance
    machinery runs on everywhere else.
    """
    result = Completion()

    unfinished = [t for t in dag.tasks
                  if t.status not in (COMPLETED, UNAVAILABLE, SKIPPED)]
    result.met[OBJECTIVES] = not unfinished
    if unfinished:
        result.reasons[OBJECTIVES] = (
            f"{len(unfinished)} of {len(dag.tasks)} tasks did not finish "
            f"({', '.join(t.objective or t.task_id for t in unfinished[:3])})")

    result.met[HYPOTHESES] = hypotheses_recorded
    if not hypotheses_recorded:
        result.reasons[HYPOTHESES] = "no hypothesis statuses were recorded"

    challenges = [t for t in dag.by_type(CHALLENGE) if t.satisfied]
    result.met[CHALLENGED] = bool(challenges)
    if not challenges:
        result.reasons[CHALLENGED] = "the challenge pass did not run"

    result.met[VALIDATED] = validations_passed
    if not validations_passed:
        result.reasons[VALIDATED] = "not every validation passed"

    result.met[FACTS] = facts > 0
    if not facts:
        result.reasons[FACTS] = "no validated facts were produced"

    result.met[GROUNDED] = grounded
    if not grounded:
        result.reasons[GROUNDED] = (
            "a figure in the narrative does not trace to a fact")

    result.met[VISUAL] = visual_approved
    if not visual_approved:
        result.reasons[VISUAL] = "the chart did not pass the Visual Critic"

    result.met[LIMITATIONS] = limitations > 0
    if not limitations:
        result.reasons[LIMITATIONS] = "no limitations were stated"

    result.met[TRACE] = trace_consistent
    if not trace_consistent:
        result.reasons[TRACE] = "the Trace does not match what ran"

    return result


__all__ = ["ANALYSIS", "BLOCKED", "BREADTH", "CHALLENGE", "CHALLENGED",
           "COMPLETED", "CONDITIONS", "CONDITION_ASKS", "CONTRADICTION",
           "CONTRIBUTION", "Completion", "Cycle", "DAG_VERSION",
           "DATA_AVAILABILITY", "DRIVER", "Dag", "Duplicate", "FACTS",
           "FAILED", "GROUNDED", "HYPOTHESES", "LIMITATIONS", "NEEDS_INPUT",
           "OBJECTIVES", "PENDING", "PERSISTENCE", "READY", "RUNNING",
           "SATISFIED", "SCOPE", "SKIPPED", "STATUSES", "SYNTHESIS",
           "TASK_TYPES", "TRACE", "TYPE_MEANS", "Task", "UNAVAILABLE",
           "UnknownDependency", "VALIDATED", "VALIDATION", "VISUAL",
           "VISUALIZATION", "completion"]
