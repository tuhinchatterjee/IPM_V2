"""Case status governance. §6.

The corpus is machine-generated and nobody is going to read 1,280 cases. That
is a legitimate way to build a corpus and a dangerous way to describe one, so
the statuses have to carry the difference honestly:

    AUTO_GENERATED              nothing has been established
    AUTO_VALIDATED              the FORM is right; the content is unexamined
    SYSTEM_REFERENCE_VALIDATED  an independent deterministic reference agreed
    HUMAN_REVIEWED              a person read it and did not approve it
    HUMAN_APPROVED              a person approved it

The load-bearing rule is §6's last line: a subjective answer-quality case
with no independent reference cannot become SYSTEM_REFERENCE_VALIDATED
because an LLM critic liked it. That is the failure this module exists to
make impossible rather than discouraged - one model approving another's work
is not evidence, and a status that said it was would launder a guess into a
production teaching case.

Retrieval and tuning eligibility are computed from status here, in one place,
so the runtime cannot drift from the policy the document states.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from backend.brain.cases import (
    AUTO_GENERATED,
    AUTO_VALIDATED,
    HUMAN_APPROVED,
    HUMAN_REVIEWED,
    RETRIEVABLE,
    STATUSES,
    SYSTEM_REFERENCE_VALIDATED,
    TUNABLE,
    Case,
    validate,
)

#: Promotions that are allowed at all. A status may always be lowered - a
#: defect found in an approved case is a reason to demote it immediately, and
#: making that require a ceremony would mean it did not happen.
PROMOTIONS: dict[str, tuple[str, ...]] = {
    AUTO_GENERATED: (AUTO_VALIDATED,),
    AUTO_VALIDATED: (SYSTEM_REFERENCE_VALIDATED, HUMAN_REVIEWED),
    SYSTEM_REFERENCE_VALIDATED: (HUMAN_REVIEWED,),
    HUMAN_REVIEWED: (HUMAN_APPROVED,),
    HUMAN_APPROVED: (),
}

#: Reference kinds that are a JUDGEMENT rather than a computation. A case
#: whose expected answer can only be settled by an opinion is not a candidate
#: for reference validation, however confident the opinion.
JUDGEMENT_KINDS: frozenset[str] = frozenset({
    "", "llm_critic", "llm_judgement", "model_opinion", "rubric_score",
    "human_impression", "answer_quality",
})


class StatusError(Exception):
    """A promotion that was refused, and why."""


@dataclass(frozen=True)
class Evidence:
    """Why a status change is justified.

    `independent` is the field that matters. It is not a label the caller
    chooses - `from_reference` sets it from what the check actually was, and
    a promotion to SYSTEM_REFERENCE_VALIDATED refuses anything else.
    """

    kind: str = ""
    #: Whether this was settled by deterministic code rather than a model.
    independent: bool = False
    #: The dimensions the reference actually checked and passed.
    dimensions: tuple[str, ...] = ()
    #: Dimensions the reference could not measure. Never counted as passes.
    not_measured: tuple[str, ...] = ()
    reviewer: str = ""
    note: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "independent": self.independent,
                "dimensions": list(self.dimensions),
                "not_measured": list(self.not_measured),
                "reviewer": self.reviewer, "note": self.note, "at": self.at}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def from_reference(report: Any) -> Evidence:
    """Evidence from a reference report. §7's output, §6's input.

    Takes the report's own account of what it checked rather than a summary,
    so a report that could not measure half the dimensions cannot present
    itself as a full validation.
    """
    passed = tuple(getattr(report, "passed_dimensions", ()) or ())
    unmeasured = tuple(getattr(report, "unmeasured_dimensions", ()) or ())
    independent = bool(getattr(report, "independent", False))
    return Evidence(
        kind=str(getattr(report, "kind", "") or "independent_reference"),
        independent=independent,
        dimensions=passed,
        not_measured=unmeasured,
        note=str(getattr(report, "summary", "") or ""),
        at=_now(),
    )


def review(reviewer: str, note: str = "") -> Evidence:
    """Evidence that a person read the case."""
    if not reviewer.strip():
        raise StatusError("a review with no reviewer is not a review")
    return Evidence(kind="human_review", independent=False,
                    reviewer=reviewer.strip(), note=note, at=_now())


def subjective(case: Case) -> bool:
    """Whether this case can only be settled by an opinion.

    Such a case is not worthless - it may still be reviewed and approved by a
    person. It simply cannot take the status that means "a deterministic
    reference agreed", because no deterministic reference can.
    """
    return (not case.reference.independent
            or case.reference.kind in JUDGEMENT_KINDS)


def may_promote(case: Case, to: str, evidence: Evidence) -> str:
    """Empty if the promotion is allowed; otherwise why it is not."""
    if to not in STATUSES:
        return f"{to!r} is not a status"
    if to == case.status:
        return ""
    if to not in PROMOTIONS.get(case.status, ()):
        return (f"{case.status} does not promote to {to}; the allowed next "
                f"steps are {PROMOTIONS.get(case.status, ()) or 'none'}")

    if to == AUTO_VALIDATED:
        faults = validate(case)
        if faults:
            return "the case does not pass format validation: " + \
                "; ".join(faults)
        return ""

    if to == SYSTEM_REFERENCE_VALIDATED:
        if subjective(case):
            return ("this case has no independent reference, so nothing "
                    "deterministic can agree with it. An LLM critic liking "
                    "the answer is not evidence, and this status would say "
                    "it was")
        if not evidence.independent:
            return ("the evidence offered is not independent. §6: one model "
                    "declaring another model correct cannot promote a case")
        if evidence.kind in JUDGEMENT_KINDS:
            return (f"the evidence is a {evidence.kind or 'judgement'}, not "
                    "a computation")
        if not evidence.dimensions:
            return "the reference passed no dimension, so it established "\
                   "nothing"
        return ""

    if to in (HUMAN_REVIEWED, HUMAN_APPROVED):
        if not evidence.reviewer.strip():
            return f"{to} requires a named person; there is none"
        return ""

    return ""


def promote(case: Case, to: str, evidence: Evidence) -> Case:
    """The case at its new status, or a refusal.

    Returns a new Case rather than mutating: a status change is a fact about
    a version, and rewriting the object in place would lose which version
    carried which claim.
    """
    problem = may_promote(case, to, evidence)
    if problem:
        raise StatusError(f"{case.case_id} cannot become {to}: {problem}")
    if to == case.status:
        return case
    return replace(case, status=to, version=case.version + 1,
                   tags=(*case.tags, f"status:{to.lower()}"))


def demote(case: Case, to: str, why: str) -> Case:
    """Lower a case's status because a defect was found.

    Always permitted, and deliberately cheap. A case discovered to be wrong
    must stop being retrievable in the same breath as the discovery; making
    that require an approval would mean it kept teaching until someone found
    the time.
    """
    if to not in STATUSES:
        raise StatusError(f"{to!r} is not a status")
    if STATUSES.index(to) >= STATUSES.index(case.status):
        raise StatusError(
            f"{to} is not lower than {case.status}; use promote()")
    if not why.strip():
        raise StatusError("a demotion with no reason cannot be reviewed later")
    return replace(case, status=to, version=case.version + 1,
                   tags=(*case.tags, f"demoted:{to.lower()}"))


# --------------------------------------------------------- production policy


def may_retrieve(status: str, *, administrator_policy: bool = False
                 ) -> tuple[bool, str]:
    """Whether a case at this status may be retrieved into a live answer.

    Returns the decision and the label the answer must carry. The label is
    not decoration: SYSTEM_REFERENCE_VALIDATED means a deterministic check
    agreed and no person has read the wording, and a client is entitled to
    know which of those they are looking at.
    """
    if status not in STATUSES:
        return False, ""
    if status == HUMAN_APPROVED:
        return True, ""
    if status == SYSTEM_REFERENCE_VALIDATED:
        if administrator_policy:
            return True, "System-validated - not reviewed by a person"
        return False, ""
    return False, ""


def may_tune(status: str) -> bool:
    """Whether a case at this status may influence prompts or policies.

    Wider than retrieval on purpose. Tuning against a case whose reference
    was computed deterministically is sound even when nobody has read the
    wording, because what is being learned is the SHAPE of a correct answer
    and the shape is what the reference checked.
    """
    return status in TUNABLE


def retrievable_cases(cases: list[Case], *,
                      administrator_policy: bool = False) -> list[Case]:
    return [c for c in cases
            if may_retrieve(c.status,
                            administrator_policy=administrator_policy)[0]]


def tunable_cases(cases: list[Case]) -> list[Case]:
    return [c for c in cases if may_tune(c.status)]


def census(cases: list[Case]) -> dict[str, int]:
    """How many cases sit at each status. What a report should show."""
    tally = dict.fromkeys(STATUSES, 0)
    for case in cases:
        tally[case.status] = tally.get(case.status, 0) + 1
    return tally


def policy_summary() -> list[dict[str, str]]:
    """The production policy as data, for the Brain Center to render.

    One source: if this and the document ever disagree, the document is
    describing something that is not running.
    """
    return [
        {"status": status,
         "retrievable": RETRIEVABLE[status] or "no",
         "may_tune": "yes" if status in TUNABLE else "no"}
        for status in STATUSES
    ]
