"""
Whether the evidence actually answers what was asked.

The failure this prevents
--------------------------
"Why has Contracting deteriorated and is it broad across the segment?" is two
questions. Run the trend, get a number, write a paragraph, and the answer
looks complete — it has a figure, a movement and a confident tone — while the
"why" was never established and the "broad or concentrated" was never
measured. Nobody notices, because the shape of a complete answer and the
shape of a third of one are the same shape.

So before any prose is written, each part of the request is checked against
what was actually executed. A part with no evidence behind it is named, and
the turn either runs one more bounded analysis or says which part it could
not answer. It never quietly drops one.

Why it does not simply run more
--------------------------------
Because that is how a bounded turn becomes an unbounded loop. A revision is
spent from the same ledger as everything else, and when the ledger will not
carry another the honest outcome is a partial answer that says what is
missing — not a smaller answer that pretends to be a whole one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning.conversation import packet as packet_mod
from backend.early_warning.conversation import plan as plan_mod

#: What each part of a request needs to have been executed for it to count
#: as covered. Keyed by the analysis the reader asked for.
COVERED_BY: dict[str, tuple[str, ...]] = {
    "diagnosis": (plan_mod.DIAGNOSIS,),
    "movement": (plan_mod.MOVEMENT,),
    "concentration": (plan_mod.CONCENTRATION,),
    "comparison": (plan_mod.COMPARISON, plan_mod.GROUPING),
    "grouping": (plan_mod.GROUPING,),
    "evidence": (plan_mod.EVIDENCE,),
    "methodology": (plan_mod.METHODOLOGY,),
}

#: What to run for a part that was asked for and not covered.
REPAIR_WITH: dict[str, str] = {
    "diagnosis": plan_mod.DIAGNOSIS,
    "movement": plan_mod.MOVEMENT,
    "concentration": plan_mod.CONCENTRATION,
    "grouping": plan_mod.GROUPING,
}


@dataclass
class Review:
    """Whether the turn may write its answer yet."""

    complete: bool = True
    covered: dict[str, bool] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    #: Claims the prose must NOT make, because nothing supports them.
    unsupported: list[str] = field(default_factory=list)
    next_step: plan_mod.Step | None = None
    recommend_partial: bool = False
    clarification: str = ""
    presentation: str = "narrative"
    engine: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete, "covered": dict(self.covered),
            "uncovered": list(self.uncovered),
            "unsupported_claims": list(self.unsupported),
            "next_step": self.next_step.to_dict() if self.next_step else None,
            "recommend_partial": self.recommend_partial,
            "required_clarification": self.clarification,
            "presentation": self.presentation,
            "engine": self.engine,
        }


def _presentation(request: Any, packet: packet_mod.ResultPacket) -> str:
    """Narrative, table or chart — decided by what the evidence is shaped like."""
    analyses = list(getattr(request, "requested_analyses", None) or [])
    if "methodology" in analyses or "evidence" in analyses:
        return "narrative"
    if len(packet.rows) >= 5:
        return "table"
    if "movement" in analyses or "concentration" in analyses:
        return "chart"
    return "narrative"


def review(request: Any, plan: plan_mod.Plan,
           packet: packet_mod.ResultPacket, *,
           can_revise: bool = True) -> Review:
    """Check every part of the request against what was executed."""
    asked = list(getattr(request, "requested_analyses", None) or [])
    if not asked:
        asked = [str(getattr(request, "requested_analysis", "") or "")] \
            if getattr(request, "requested_analysis", "") else []

    ran = {step.get("analysis") for step in packet.steps}
    covered: dict[str, bool] = {}
    for part in asked:
        needed = COVERED_BY.get(part)
        covered[part] = True if needed is None else bool(ran & set(needed))

    uncovered = [part for part, ok in covered.items() if not ok]

    # The subquestions the reader wrote, checked the same way: a question
    # that named two things and produced evidence for one is incomplete
    # whatever its analyses list says.
    unsupported: list[str] = []
    for sub in list(getattr(request, "subquestions", None) or [])[:6]:
        if _asks_for_names(sub) and not packet.rows:
            unsupported.append(
                "which obligors — no obligor-level rows were returned")

    out = Review(covered=covered, uncovered=uncovered,
                 unsupported=unsupported,
                 presentation=_presentation(request, packet))

    if not uncovered and not unsupported:
        out.complete = True
        return out

    out.complete = False
    first = next((p for p in uncovered if p in REPAIR_WITH), "")
    if first and can_revise:
        out.next_step = plan_mod.Step(
            analysis=REPAIR_WITH[first],
            period=packet.period,
            comparison_period=packet.comparison_period,
            filters=dict(packet.filters),
            measures=list(plan_mod.BASE_MEASURES),
            rationale=(f"The request asked for a {first} and the first "
                       f"execution did not produce one, so it is run now "
                       f"rather than left out of the answer."))
    else:
        # No affordable revision. The answer is partial and has to say so;
        # an answer that stops early and does not is the failure this whole
        # review exists to prevent.
        out.recommend_partial = True
    return out


def _asks_for_names(text: str) -> bool:
    return bool(re.search(
        r"\bwhich (names?|borrowers?|obligors?|customers?)\b|\bwho\b|"
        r"\bname the\b|\blist the\b", text or "", re.I))


__all__ = ["COVERED_BY", "REPAIR_WITH", "Review", "review"]
