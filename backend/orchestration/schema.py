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
from typing import Any

# A plan longer than this is a sign the question was not understood. Five steps
# is enough for any question in the demonstration set and keeps a single
# investigation inside a few seconds.
MAX_PLAN_STEPS = 5


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "title": self.title,
            "rationale": self.rationale,
            "params": dict(self.params),
            "filters": dict(self.filters),
            "period": self.period,
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
        )

    def with_params(self, **changes: Any) -> PlanStep:
        merged = {**self.params, **changes}
        return PlanStep(
            analysis_id=self.analysis_id, title=self.title, rationale=self.rationale,
            params=merged, filters=dict(self.filters), period=self.period,
        )

    def with_filters(self, filters: dict[str, Any]) -> PlanStep:
        return PlanStep(
            analysis_id=self.analysis_id, title=self.title, rationale=self.rationale,
            params=dict(self.params), filters=dict(filters), period=self.period,
        )


@dataclass(frozen=True)
class AnalysisPlan:
    """A complete investigation: how the question was read, and what to run."""

    question: str
    # A restatement of the question in IPM's own terms — what the user is
    # understood to be asking. Displayed, so the user can see a misreading.
    intent: str
    steps: list[PlanStep]
    # "demo" when no model key is configured; otherwise the provider name.
    planner: str = "demo"
    model_name: str | None = None
    # Questions worth asking next. Selected from the registered library, so every
    # suggestion is something IPM can actually answer.
    follow_ups: list[str] = field(default_factory=list)
    # Set when the question could not be matched to any registered analysis.
    unmatched: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
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
            steps=[PlanStep.from_dict(s) for s in payload.get("steps") or []],
            planner=str(payload.get("planner") or "demo"),
            model_name=payload.get("model_name"),
            follow_ups=list(payload.get("follow_ups") or []),
            unmatched=bool(payload.get("unmatched")),
            notes=list(payload.get("notes") or []),
        )

    def replace_steps(self, steps: list[PlanStep]) -> AnalysisPlan:
        return AnalysisPlan(
            question=self.question, intent=self.intent, steps=steps,
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


__all__ = ["MAX_PLAN_STEPS", "AnalysisPlan", "PlanRejected", "PlanStep"]
