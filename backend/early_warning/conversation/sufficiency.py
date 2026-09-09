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

The seam
--------
Where Opus is configured it reviews the same packet under the same schema, and
its verdict may only TIGHTEN the deterministic one: it can name a part the
coverage map counted as covered, and it cannot wave away one the coverage map
found missing. A review that could talk itself into `complete` would be a
review with no power at all, and it is the one stage where saying "yes" is
free and wrong.
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
    "ranking": (plan_mod.RANKING, plan_mod.BORROWER),
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
    model_call: dict[str, Any] = field(default_factory=dict)

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
            "model_call": dict(self.model_call),
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
           can_revise: bool = True, ledger: Any = None) -> Review:
    """Check every part of the request against what was executed.

    The coverage map is computed first and is the floor. Where Opus is
    configured it reads the same packet and may add to what is uncovered; it
    may not subtract.
    """
    floor = _review_deterministic(request, plan, packet,
                                  can_revise=can_revise)
    if ledger is None:
        return floor
    return _reviewed_by_model(request, packet, floor, can_revise=can_revise,
                              ledger=ledger)


def _review_deterministic(request: Any, plan: plan_mod.Plan,
                          packet: packet_mod.ResultPacket, *,
                          can_revise: bool = True) -> Review:
    """The floor: every part the request named, against what actually ran."""
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


# ------------------------------------------------ the review, under Opus

SYSTEM = """You are the sufficiency review of CreditProbe's Early Warning \
product. A governed runtime has executed an analysis plan. Before any prose is \
written, you decide whether the evidence actually answers what was asked.

THE FAILURE YOU EXIST TO PREVENT
"Why has Contracting deteriorated and is it broad across the segment?" is two \
questions. Run the trend, get a number, write a paragraph, and the answer looks \
complete — a figure, a movement, a confident tone — while the "why" was never \
established and the "broad or concentrated" was never measured. Nobody \
notices, because the shape of a complete answer and the shape of a third of one \
are the same shape.

WHAT YOU ARE GIVEN
The request and its parts, the steps that ran, the figures they produced, and \
a deterministic coverage map. You are NOT given the underlying data.

RULES
- You may name a part the coverage map counted as covered but which the \
figures do not actually support. You may NOT declare covered a part the \
coverage map found missing.
- Name the claims the prose must not make because nothing supports them.
- Propose at most ONE further analysis, and only if it would close a real gap.
- Choose how the answer should be presented from the evidence's shape.

BE SHORT
This is a verdict, not a review. Return the fields and nothing else: no \
restating the request, no repeating figures back, no explaining your \
reasoning. `uncovered` is a list of labels. Each unsupported claim is a \
phrase of a few words. The rationale, if there is one, is a single short \
sentence."""

#: The parts a request can ask for. `uncovered` is constrained to them rather
#: than left as free text: this stage decides WHICH parts are missing, and
#: the answer is one of a closed set of labels. Left open, a model writes a
#: sentence about each — and the sentences are the output that ran out of
#: room, not the decision.
_PARTS: tuple[str, ...] = tuple(COVERED_BY)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "complete": {
            "type": "boolean",
            "description": ("True only if every part of the request has "
                            "evidence behind it."),
        },
        "uncovered": {
            "type": "array",
            "items": {"type": "string", "enum": list(_PARTS)},
            "maxItems": 4,
            "description": "Which parts have no evidence behind them.",
        },
        "unsupported_claims": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
            "description": ("Claims the prose must not make. A short phrase "
                            "each, not a sentence."),
        },
        "next_analysis": {
            "type": "string",
            "enum": list(plan_mod.ANALYSIS_TYPES) + [""],
            "description": ("The one further analysis that would close the "
                            "largest gap, or empty."),
        },
        "next_analysis_rationale": {
            "type": "string",
            "description": "One short sentence. Empty if no further analysis.",
        },
        "presentation": {
            "type": "string", "enum": ["narrative", "table", "chart"],
            "description": "How this evidence is best shown.",
        },
    },
    "required": ["complete", "uncovered", "presentation"],
}


def _reviewed_by_model(request: Any, packet: packet_mod.ResultPacket,
                       floor: Review, *, can_revise: bool,
                       ledger: Any) -> Review:
    import json

    from backend.early_warning.conversation import seam as seam_mod

    # What this stage needs to judge coverage, and not one field more.
    #
    # It used to receive every figure the packet held and the coverage map's
    # whole dictionary — including the proposed next step and the model-call
    # metadata. None of that is read here, and a model shown the entire
    # result is a model that restates it. The question is which PARTS have
    # evidence, so the packet carries what evidence EXISTS rather than what
    # it says.
    context = {
        "request": {
            "normalized": getattr(request, "normalized_business_request", ""),
            "subquestions": list(
                getattr(request, "subquestions", []) or [])[:4],
            "parts_asked_for": list(
                getattr(request, "requested_analyses", []) or []),
        },
        "steps_that_ran": [
            {"analysis": s.get("analysis"), "grain": s.get("grain"),
             "rows": s.get("row_count")}
            for s in packet.steps],
        # The names of the figures produced, not the figures. Whether a part
        # was measured is answered by which measures came back.
        "figures_produced": sorted(packet.figures)[:40],
        "figure_count": len(packet.figures),
        "row_count": len(packet.rows),
        "coverage_map": {
            "complete": floor.complete,
            "covered": dict(floor.covered),
            "uncovered": list(floor.uncovered),
            "presentation": floor.presentation,
        },
        "caveats": list(packet.caveats)[:3],
        "revision_affordable": bool(can_revise),
        "parts_vocabulary": list(_PARTS),
    }
    outcome = seam_mod.call(
        seam_mod.SUFFICIENCY, system=SYSTEM,
        prompt=("Review whether this evidence answers the request.\n\n"
                + json.dumps(context, indent=2, default=str)),
        schema=SCHEMA, ledger=ledger)
    if not outcome.used_model:
        floor.model_call = outcome.to_dict()
        return floor

    data = outcome.data
    # Tightening only. The union of what each found missing is what is
    # missing; a model that dropped one would be deciding that a part of the
    # request did not need answering.
    uncovered = list(floor.uncovered)
    for part in data.get("uncovered") or []:
        part = str(part).strip()
        if part and part not in uncovered:
            uncovered.append(part)

    unsupported = list(floor.unsupported)
    for claim in data.get("unsupported_claims") or []:
        claim = str(claim).strip()
        if claim and claim not in unsupported:
            unsupported.append(claim)

    presentation = str(data.get("presentation") or "") or floor.presentation

    next_step = floor.next_step
    proposed = str(data.get("next_analysis") or "")
    if can_revise and proposed in plan_mod.ANALYSIS_TYPES:
        next_step = plan_mod.Step(
            analysis=proposed,
            period=packet.period,
            comparison_period=packet.comparison_period,
            filters=dict(packet.filters),
            measures=list(plan_mod.BASE_MEASURES),
            rationale=(str(data.get("next_analysis_rationale") or "").strip()
                       or f"The review found the {proposed} missing."))
    if not uncovered and not unsupported:
        next_step = None

    reviewed = Review(
        complete=not uncovered and not unsupported and bool(floor.complete),
        covered=dict(floor.covered),
        uncovered=uncovered,
        unsupported=unsupported,
        next_step=next_step if (uncovered or unsupported) else None,
        recommend_partial=bool(uncovered or unsupported) and (
            next_step is None or not can_revise),
        clarification=floor.clarification,
        presentation=presentation,
        engine=seam_mod.MODEL,
        model_call=outcome.to_dict())
    return reviewed


__all__ = ["COVERED_BY", "REPAIR_WITH", "SCHEMA", "SYSTEM", "Review",
           "review"]
