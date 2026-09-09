"""
Investigation budgets, by question class. Brief §7.5.

The base build capped planning at four turns for every question, so a judgement
question spent most of its budget on orientation. These are class-dependent
instead — and they are EXPERIMENT SETTINGS, not measured optima. The brief is
explicit about that and so is this docstring: nobody has demonstrated that
eight turns answers a complex question better than six.

The budget actually used is recorded on the Trace, so a later measurement can
replace these numbers with evidence rather than with another guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.cockpit_v2 import understand as understand_mod

#: A definition, a glossary lookup, a single stated figure. No investigation.
CLASS_SIMPLE = "simple"
#: One capability over one scope. The ordinary Cockpit question.
CLASS_STANDARD = "standard"
#: Several capabilities, or a factor decomposition with entity drill-down.
CLASS_COMPLEX = "complex"

#: Proposed starting caps. Experiment settings, per brief §7.5.
BUDGETS: dict[str, dict[str, int]] = {
    CLASS_SIMPLE: {"planning_turns": 1, "tool_calls": 2,
                   "wall_clock_seconds": 15},
    CLASS_STANDARD: {"planning_turns": 4, "tool_calls": 10,
                     "wall_clock_seconds": 60},
    CLASS_COMPLEX: {"planning_turns": 8, "tool_calls": 20,
                    "wall_clock_seconds": 120},
}

#: Outputs that on their own make a question complex.
_COMPLEX_OUTPUTS = frozenset({
    understand_mod.ECL_FACTOR_DECOMPOSITION, understand_mod.PD_IMPACT,
    understand_mod.RATIO_MOVEMENT})


@dataclass(frozen=True)
class Budget:
    question_class: str
    planning_turns: int
    tool_calls: int
    wall_clock_seconds: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"question_class": self.question_class,
                "planning_turns": self.planning_turns,
                "tool_calls": self.tool_calls,
                "wall_clock_seconds": self.wall_clock_seconds,
                "reason": self.reason,
                "note": ("Experiment settings, not measured optima. The "
                         "budget actually used is recorded so these can be "
                         "replaced by evidence.")}


def classify(request: understand_mod.Request) -> str:
    outputs = set(request.outputs)
    if outputs and outputs <= {understand_mod.DEFINITION}:
        return CLASS_SIMPLE
    if outputs & _COMPLEX_OUTPUTS or len(outputs) >= 3:
        return CLASS_COMPLEX
    return CLASS_STANDARD


def for_request(request: understand_mod.Request) -> Budget:
    question_class = classify(request)
    caps = BUDGETS[question_class]
    if question_class == CLASS_SIMPLE:
        reason = ("A definition needs no investigation and no chart, so it "
                  "gets the smallest budget rather than the standard one.")
    elif question_class == CLASS_COMPLEX:
        reason = (f"{len(request.outputs)} requested output(s), including a "
                  f"factor decomposition, so the larger budget applies.")
    else:
        reason = "One capability over one scope."
    return Budget(question_class=question_class,
                  planning_turns=caps["planning_turns"],
                  tool_calls=caps["tool_calls"],
                  wall_clock_seconds=caps["wall_clock_seconds"],
                  reason=reason)


__all__ = ["BUDGETS", "Budget", "CLASS_COMPLEX", "CLASS_SIMPLE",
           "CLASS_STANDARD", "classify", "for_request"]
