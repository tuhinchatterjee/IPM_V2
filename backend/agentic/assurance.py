"""
Answer Assurance. §54.

    "Do not show LLM self-confidence as the answer confidence."

That instruction is the whole design. A model's stated confidence is a
prediction about its own output made by the thing that produced it, and it is
uncorrelated with whether the ECL figure on the screen reconciles to the source.
Showing it beside a credit number tells a reader something false in the register
they trust most.

So assurance is computed from what actually happened:

    data completeness        did every source the plan needed have the period?
    relationship validation  did the joins run over governed relationships?
    method certification     was a certified method used, or an ad-hoc plan?
    plan validation          did the IR validate against governed metadata?
    business invariants      did the result satisfy its concepts' invariants?
    reconciliation           do the totals agree with the sources?
    evidence grounding       does every figure in the prose appear in a result?
    model agreement          did the plan need repairing, and did specialists
                             disagree?
    known limitations        what the run itself recorded as not done

Each is a component with a state and a sentence. The overall status is the
weakest link, not an average: a result that fails its invariants is not
"mostly assured" because seven other checks passed.

Four statuses
-------------
    HIGH ASSURANCE   everything checked, everything passed
    VALIDATED        checked and passed, with something not applicable
    LIMITED EVIDENCE something material could not be checked
    NEEDS REVIEW     something checked did not pass

"Needs review" is deliberately not "failed". A failed invariant blocks the
answer entirely (that is `orchestration/invariants.py`'s job and is unchanged);
what reaches assurance is a result good enough to show and specific enough to
question.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

PASSED = "passed"
FAILED = "failed"
PARTIAL = "partial"
NOT_APPLICABLE = "not_applicable"
NOT_CHECKED = "not_checked"

HIGH = "HIGH ASSURANCE"
VALIDATED = "VALIDATED"
LIMITED = "LIMITED EVIDENCE"
NEEDS_REVIEW = "NEEDS REVIEW"

STATUS_MEANING: dict[str, str] = {
    HIGH: "Every check CreditProbe can run on this answer passed.",
    VALIDATED: ("The calculations were checked and passed. Some checks did "
                "not apply to this kind of answer."),
    LIMITED: ("The calculations passed, but something material could not be "
              "checked. Read the components before relying on it."),
    NEEDS_REVIEW: ("A check did not pass. The figures are shown so they can "
                   "be questioned, not because they are settled."),
}

#: Components in the order a reader should meet them: what the answer was built
#: from, then whether the arithmetic held, then whether the prose matches.
ORDER: tuple[str, ...] = (
    "data_completeness",
    "relationship_validation",
    "method_certification",
    "plan_validation",
    "business_invariants",
    "reconciliation",
    "evidence_grounding",
    "model_agreement",
    "known_limitations",
    # P0.9. Added last because it is a statement about the OTHER components:
    # whether the run left behind the evidence they claim to have assessed.
    "trace_consistency",
)

LABELS: dict[str, str] = {
    "data_completeness": "Data completeness",
    "relationship_validation": "Relationship validation",
    "method_certification": "Method certification",
    "plan_validation": "Plan validation",
    "business_invariants": "Business invariants",
    "reconciliation": "Reconciliation",
    "evidence_grounding": "Evidence grounding",
    "model_agreement": "Agreement and repair",
    "known_limitations": "Known limitations",
    "trace_consistency": "Trace consistency",
}

#: Which components must be checked for an answer to be more than LIMITED. A
#: result nobody reconciled is not a result to rely on, however confident
#: anything sounds about it.
MATERIAL: frozenset[str] = frozenset(
    {"business_invariants", "plan_validation", "evidence_grounding"})


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """One check, its state, and what it means."""

    key: str
    state: str
    detail: str
    #: Numbers behind the state, where there are any.
    figures: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS.get(self.key, self.key.replace("_", " ").title())

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "state": self.state,
                "detail": self.detail, "figures": dict(self.figures)}


@dataclass
class Assurance:
    """What can be said about how much this answer can be relied on."""

    status: str = LIMITED
    components: list[Component] = field(default_factory=list)
    #: Set where a specific thing stops this being higher.
    weakest: str = ""

    @property
    def meaning(self) -> str:
        return STATUS_MEANING.get(self.status, "")

    def component(self, key: str) -> Component | None:
        return next((c for c in self.components if c.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "meaning": self.meaning,
            "weakest": self.weakest,
            "components": [c.to_dict() for c in self.components],
            "passed": sum(1 for c in self.components if c.state == PASSED),
            "checked": sum(1 for c in self.components
                           if c.state in (PASSED, FAILED, PARTIAL)),
        }


# ---------------------------------------------------------------------------
# Computing it
# ---------------------------------------------------------------------------


def assess(*, plan: Any = None, tasks: list[Any] | None = None,
           invariants: Any = None, grounding: Any = None,
           reconciliation: dict[str, Any] | None = None,
           conflicts: list[Any] | None = None,
           repairs: int = 0, certified: bool = False,
           relationships_used: int = 0, relationships_governed: int = 0,
           periods_expected: int = 0, periods_found: int = 0,
           limitations: list[str] | None = None) -> Assurance:
    """Build the assurance view from what the run recorded.

    Every argument is something the run either observed or did not. Nothing
    here asks a model anything, and nothing here has a default that flatters:
    an absent invariant result is NOT_CHECKED, which lowers the status, rather
    than being treated as a pass.
    """
    found: list[Component] = []
    task_list = list(tasks or [])

    found.append(_completeness(periods_expected, periods_found, task_list))
    found.append(_relationships(relationships_used, relationships_governed))
    found.append(_method(certified))
    found.append(_plan(plan, task_list))
    found.append(_invariants(invariants))
    found.append(_reconciliation(reconciliation))
    found.append(_grounding(grounding))
    found.append(_agreement(conflicts or [], repairs))
    found.append(_limitations(limitations or [], task_list))

    ordered = sorted(found, key=lambda c: ORDER.index(c.key)
                     if c.key in ORDER else len(ORDER))
    return Assurance(status=_status(ordered), components=ordered,
                     weakest=_weakest(ordered))


def _status(components: list[Component]) -> str:
    """The weakest link, not the average."""
    states = {c.key: c.state for c in components}
    if any(s == FAILED for s in states.values()):
        return NEEDS_REVIEW
    if any(states.get(k) in (NOT_CHECKED, PARTIAL) for k in MATERIAL):
        return LIMITED
    if any(s == PARTIAL for s in states.values()):
        return LIMITED
    if any(s == NOT_APPLICABLE for s in states.values()):
        return VALIDATED
    if all(s == PASSED for s in states.values()):
        return HIGH
    return VALIDATED


def _weakest(components: list[Component]) -> str:
    for state in (FAILED, PARTIAL, NOT_CHECKED):
        for component in components:
            if component.state == state:
                return component.key
    return ""


# -- individual checks ------------------------------------------------------


def _completeness(expected: int, found: int, tasks: list[Any]) -> Component:
    blocked = [t for t in tasks if getattr(t, "status", "") == "blocked"]
    if expected and found < expected:
        return Component(
            "data_completeness", PARTIAL,
            f"{found} of {expected} periods the answer needed are published.",
            {"expected": expected, "found": found})
    if blocked:
        return Component(
            "data_completeness", PARTIAL,
            f"{len(blocked)} part(s) of the review could not run because the "
            f"data they needed is not available.",
            {"blocked": len(blocked)})
    if not expected:
        return Component("data_completeness", NOT_APPLICABLE,
                         "This answer does not depend on a period being "
                         "complete.")
    return Component("data_completeness", PASSED,
                     f"All {expected} period(s) the answer needed are "
                     f"published.", {"expected": expected})


def _relationships(used: int, governed: int) -> Component:
    if used == 0:
        return Component("relationship_validation", NOT_APPLICABLE,
                         "The answer came from one dataset; nothing was "
                         "joined.")
    if governed < used:
        return Component(
            "relationship_validation", FAILED,
            f"{used - governed} of {used} joins are not governed "
            f"relationships.", {"used": used, "governed": governed})
    return Component("relationship_validation", PASSED,
                     f"All {used} join(s) used governed relationships.",
                     {"used": used})


def _method(certified: bool) -> Component:
    if certified:
        return Component("method_certification", PASSED,
                         "A certified method produced this answer.")
    return Component(
        "method_certification", NOT_APPLICABLE,
        "This answer was composed for the question rather than run from a "
        "certified method. It is validated the same way; it does not carry a "
        "certification.")


def _plan(plan: Any, tasks: list[Any]) -> Component:
    if plan is None and not tasks:
        return Component("plan_validation", NOT_CHECKED,
                         "No plan was recorded for this answer.")
    rejected = [t for t in tasks if getattr(t, "error_category", "")
                == "plan_rejected"]
    if rejected:
        return Component("plan_validation", FAILED,
                         f"{len(rejected)} plan(s) were rejected by the "
                         f"validator.")
    return Component("plan_validation", PASSED,
                     "Every plan validated against the governed metadata "
                     "before it ran.")


def _invariants(result: Any) -> Component:
    if result is None:
        return Component("business_invariants", NOT_CHECKED,
                         "No invariant check was recorded.")
    checked = int(getattr(result, "checked", 0)
                  or len(getattr(result, "checks", ()) or ()))
    failures = list(getattr(result, "failures", ()) or ())
    if failures:
        return Component("business_invariants", FAILED,
                         f"{len(failures)} invariant(s) did not hold: "
                         f"{'; '.join(str(f) for f in failures[:3])}.",
                         {"checked": checked, "failed": len(failures)})
    if not checked:
        return Component("business_invariants", NOT_APPLICABLE,
                         "The concepts in this answer carry no invariants.")
    return Component("business_invariants", PASSED,
                     f"All {checked} invariant(s) held.", {"checked": checked})


def _reconciliation(found: dict[str, Any] | None) -> Component:
    if not found:
        return Component("reconciliation", NOT_CHECKED,
                         "No reconciliation was recorded for this answer.")
    difference = found.get("difference")
    if difference in (None, ""):
        return Component("reconciliation", NOT_CHECKED,
                         "Reconciliation was attempted but produced no "
                         "figure.")
    try:
        gap = abs(float(difference))
    except (TypeError, ValueError):
        return Component("reconciliation", NOT_CHECKED,
                         "The reconciliation figure could not be read.")
    tolerance = float(found.get("tolerance", 0.01) or 0.01)
    if gap > tolerance:
        return Component("reconciliation", FAILED,
                         f"The result does not reconcile to its sources "
                         f"(difference {gap:,.4f}).", dict(found))
    return Component("reconciliation", PASSED,
                     "The result reconciles to its sources.", dict(found))


def _grounding(result: Any) -> Component:
    if result is None:
        return Component("evidence_grounding", NOT_CHECKED,
                         "The written answer was not checked against the "
                         "computed figures.")
    ungrounded = list(getattr(result, "ungrounded", ()) or ())
    if ungrounded:
        return Component("evidence_grounding", FAILED,
                         f"{len(ungrounded)} figure(s) in the written answer "
                         f"do not appear in the result.",
                         {"ungrounded": ungrounded[:5]})
    return Component("evidence_grounding", PASSED,
                     "Every figure in the written answer appears in the "
                     "computed result.")


def _agreement(conflicts: list[Any], repairs: int) -> Component:
    open_conflicts = [c for c in conflicts if not getattr(c, "resolved", True)]
    if open_conflicts:
        return Component(
            "model_agreement", PARTIAL,
            f"{len(open_conflicts)} disagreement(s) between specialists could "
            f"not be settled by the evidence and are reported as they stand.",
            {"unresolved": len(open_conflicts), "total": len(conflicts)})
    if conflicts:
        return Component(
            "model_agreement", PASSED,
            f"{len(conflicts)} disagreement(s) were settled against the "
            f"deterministic evidence.", {"resolved": len(conflicts)})
    if repairs:
        return Component("model_agreement", PASSED,
                         f"The plan was repaired {repairs} time(s) before it "
                         f"validated.", {"repairs": repairs})
    return Component("model_agreement", PASSED,
                     "No plan needed repairing and no specialist disagreed.")


def _limitations(limitations: list[str], tasks: list[Any]) -> Component:
    stated = list(limitations)
    for task in tasks:
        if getattr(task, "status", "") in ("failed", "blocked"):
            note = (getattr(task, "error", "")
                    or f"{getattr(task, 'purpose', 'a component')} did not "
                       f"complete")
            stated.append(str(note))
    if not stated:
        return Component("known_limitations", PASSED,
                         "Nothing was left undone.")
    return Component("known_limitations", PARTIAL,
                     f"{len(stated)} limitation(s): "
                     f"{'; '.join(stated[:3])}.",
                     {"limitations": stated[:8]})


__all__ = [
    "FAILED",
    "HIGH",
    "LABELS",
    "LIMITED",
    "MATERIAL",
    "NEEDS_REVIEW",
    "NOT_APPLICABLE",
    "NOT_CHECKED",
    "ORDER",
    "PARTIAL",
    "PASSED",
    "STATUS_MEANING",
    "VALIDATED",
    "Assurance",
    "Component",
    "assess",
]
