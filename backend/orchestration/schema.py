"""
The plan contract — the only thing a language model is allowed to produce.

A plan is not code and it is not a query. It is a short, declarative list of
registered IPM analyses to run, each with parameters the analysis's own contract
already permits. That is the whole vocabulary available to the planner:

    {"analysis_id": "stage_migration",
     "params": {"from_period": "previous", "to_period": "latest", "basis": "ead"},
     "filters": {"sector": "Real Estate"}}

There is deliberately no field for SQL, no field for a file path, no field for
an expression, and no field for a number. A model that wants to invent a figure
has nowhere to put it, and a model that names something unregistered is rejected
by the validator before anything runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# A plan longer than this is a sign the question was not understood. Five steps
# is enough for any question in the demonstration set and keeps a single
# investigation inside a few seconds.
MAX_PLAN_STEPS = 5


class StepRole(StrEnum):
    """Why a step is in the plan.

    Exactly one step is PRIMARY: the analysis that answers the question. A
    SUPPORTING step is only permitted where it materially helps explain the
    primary result — not because it is adjacent, and not because it is
    interesting. This is what stops "which sectors deteriorated?" from
    returning a general portfolio briefing.
    """

    PRIMARY = "primary"
    SUPPORTING = "supporting"


@dataclass(frozen=True)
class PlanStep:
    """One registered analysis to run, and why."""

    analysis_id: str
    # What this step contributes, in the user's language. Shown as the heading of
    # the result block, so it must read as a finding rather than a function name.
    title: str = ""
    # One sentence explaining why this step was selected. This is interpretation,
    # never arithmetic.
    rationale: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    period: str | None = None
    role: StepRole = StepRole.PRIMARY

    @property
    def is_primary(self) -> bool:
        return self.role is StepRole.PRIMARY

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "title": self.title,
            "rationale": self.rationale,
            "params": dict(self.params),
            "filters": dict(self.filters),
            "period": self.period,
            "role": self.role.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanStep:
        return cls(
            analysis_id=str(payload.get("analysis_id") or payload.get("fn") or ""),
            title=str(payload.get("title") or ""),
            rationale=str(payload.get("rationale") or ""),
            params=dict(payload.get("params") or {}),
            filters=dict(payload.get("filters") or {}),
            period=payload.get("period"),
            role=StepRole(payload.get("role") or StepRole.PRIMARY),
        )

    def with_params(self, **changes: Any) -> PlanStep:
        merged = {**self.params, **changes}
        return PlanStep(
            analysis_id=self.analysis_id, title=self.title, rationale=self.rationale,
            params=merged, filters=dict(self.filters), period=self.period, role=self.role,
        )

    def with_filters(self, filters: dict[str, Any]) -> PlanStep:
        return PlanStep(
            analysis_id=self.analysis_id, title=self.title, rationale=self.rationale,
            params=dict(self.params), filters=dict(filters), period=self.period,
            role=self.role,
        )


@dataclass(frozen=True)
class Scope:
    """What the question actually asked for.

    Recorded rather than inferred at render time, because the whole point of
    question-scoped answering is that the reading of the question is a decision
    IPM made, is displayed, and appears on the Trace.
    """

    #: One phrase naming the subject, e.g. "sector deterioration".
    focus: str = ""
    #: The dimension the answer should be broken down by, if any.
    dimension: str | None = None
    #: The shape of answer expected — drives the one primary visual.
    output: str = "level"
    #: How much history the primary analysis needs.
    period_requirement: str = "point_in_time"
    #: Whether the question settled the period, and to what.
    period_specified: bool = False
    from_period: str | None = None
    to_period: str | None = None
    period_source: str = ""
    #: Governed filters read out of the question.
    filters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus": self.focus,
            "dimension": self.dimension,
            "output": self.output,
            "period_requirement": self.period_requirement,
            "period_specified": self.period_specified,
            "from_period": self.from_period,
            "to_period": self.to_period,
            "period_source": self.period_source,
            "filters": dict(self.filters),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Scope:
        payload = payload or {}
        return cls(
            focus=str(payload.get("focus") or ""),
            dimension=payload.get("dimension"),
            output=str(payload.get("output") or "level"),
            period_requirement=str(payload.get("period_requirement") or "point_in_time"),
            period_specified=bool(payload.get("period_specified")),
            from_period=payload.get("from_period"),
            to_period=payload.get("to_period"),
            period_source=str(payload.get("period_source") or ""),
            filters=dict(payload.get("filters") or {}),
        )


@dataclass(frozen=True)
class Clarification:
    """A question IPM asks back, instead of guessing.

    Returned in place of an answer. It carries options resolved to real
    reporting periods, so answering is a click and the executor receives values
    it can run with rather than free text it has to parse.
    """

    kind: str                    # currently only "period"
    question: str
    detail: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    #: The analysis that needs the answer, for the "why are you asking?" line.
    because: str = ""
    allow_custom: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "detail": self.detail,
            "options": list(self.options),
            "because": self.because,
            "allow_custom": self.allow_custom,
        }


@dataclass(frozen=True)
class AnalysisPlan:
    """A complete investigation: how the question was read, and what to run."""

    question: str
    # A restatement of the question in IPM's own terms — what the user is
    # understood to be asking. Displayed, so the user can see a misreading.
    intent: str
    steps: list[PlanStep]
    # What the question asked for. Empty on a plan built before scoping existed.
    scope: Scope = field(default_factory=Scope)
    # "demo" when no model key is configured; otherwise the provider name.
    planner: str = "demo"
    model_name: str | None = None
    # Questions worth asking next. Selected from the registered library, so every
    # suggestion is something IPM can actually answer.
    follow_ups: list[str] = field(default_factory=list)
    # Set when the question could not be matched to any registered analysis.
    unmatched: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def primary(self) -> PlanStep | None:
        """The analysis that answers the question."""
        for step in self.steps:
            if step.is_primary:
                return step
        return self.steps[0] if self.steps else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "scope": self.scope.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
            "planner": self.planner,
            "model_name": self.model_name,
            "follow_ups": list(self.follow_ups),
            "unmatched": self.unmatched,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AnalysisPlan:
        return cls(
            question=str(payload.get("question") or ""),
            intent=str(payload.get("intent") or ""),
            scope=Scope.from_dict(payload.get("scope") or {}),
            steps=[PlanStep.from_dict(s) for s in payload.get("steps") or []],
            planner=str(payload.get("planner") or "demo"),
            model_name=payload.get("model_name"),
            follow_ups=list(payload.get("follow_ups") or []),
            unmatched=bool(payload.get("unmatched")),
            notes=list(payload.get("notes") or []),
        )

    def replace_steps(self, steps: list[PlanStep]) -> AnalysisPlan:
        return AnalysisPlan(
            question=self.question, intent=self.intent, scope=self.scope, steps=steps,
            planner=self.planner, model_name=self.model_name,
            follow_ups=list(self.follow_ups), unmatched=self.unmatched,
            notes=list(self.notes),
        )


class PlanRejected(ValueError):
    """A plan violated the contract and will not be executed.

    Carries every reason rather than the first, because a rejection is shown to
    the user and "which of the things I asked for were refused" is the useful
    answer.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


__all__ = [
    "MAX_PLAN_STEPS",
    "AnalysisPlan",
    "Clarification",
    "PlanRejected",
    "PlanStep",
    "Scope",
    "StepRole",
]
