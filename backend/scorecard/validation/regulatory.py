"""Where the evidence for a supervisory expectation would be found. §30.

What this module is
-------------------
A map from a written supervisory expectation to the validation tests whose
results would be the evidence for it, and a coverage report saying which of
those tests actually produced a number on this run.

What it is not
--------------
It is not a compliance assessment, and nothing in it may be read as one.
This engine has no standing to say a model complies with anything. A
supervisor decides that, on a submission, after reading the evidence and
asking questions the software was never asked. Two consequences, and both
are enforced rather than merely stated:

  * The status vocabulary has no word for "compliant". A requirement is
    EVIDENCED, PARTIALLY EVIDENCED, NOT EVIDENCED or NOT APPLICABLE, and
    each of those is a statement about *this engine's own output*, not about
    the model's regulatory standing.
  * `DISCLAIMER` travels on every response this module produces, because a
    coverage table separated from its disclaimer is a compliance claim the
    moment it is pasted into a slide.

The references themselves
-------------------------
The article references are the ones already recorded on the test registry,
which is where they belong: a test knows what it evidences, and a second
list here would be a second opinion about the same thing. This module reads
them rather than restating them, and a test added to the registry with a
reference appears in this coverage automatically.

The summaries below describe what each reference asks for in the engine's
own words. They are a reading aid, not a quotation, and they say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import states

REGULATORY_VERSION = "1.0.0"

DISCLAIMER = (
    "This is a map from supervisory expectations to the validation tests "
    "that would evidence them, and a report of which of those tests produced "
    "a result. It is not a compliance assessment. CreditProbe has no "
    "standing to determine whether a model complies with any regulation, and "
    "nothing here should be represented to a supervisor, a committee or an "
    "auditor as a compliance conclusion."
)

FRAMEWORK = "CBUAE Model Management Standards and Guidance"

SUMMARIES_ARE_A_READING_AID = (
    "The descriptions below are this engine's summary of what each reference "
    "asks for. They are not quotations, and the published text governs."
)

EVIDENCED = "EVIDENCED"
PARTIALLY_EVIDENCED = "PARTIALLY EVIDENCED"
NOT_EVIDENCED = "NOT EVIDENCED"
NOT_APPLICABLE = "NOT APPLICABLE"

STATUSES: tuple[str, ...] = (EVIDENCED, PARTIALLY_EVIDENCED, NOT_EVIDENCED,
                             NOT_APPLICABLE)

STATUS_MEANING: dict[str, str] = {
    EVIDENCED: "Every test mapped to this reference produced a result on "
               "this run. Whether the results are satisfactory is a separate "
               "question, answered by the results themselves.",
    PARTIALLY_EVIDENCED: "Some of the mapped tests produced a result and "
                         "some did not. The report states which, and why "
                         "each one that did not could not.",
    NOT_EVIDENCED: "No mapped test produced a result. This reference is not "
                   "evidenced by this run at all.",
    NOT_APPLICABLE: "Every mapped test is inapplicable to this model — it "
                    "has no score-to-PD mapping, no challenger, or no "
                    "decision file. Inapplicability is a fact about the "
                    "model, not a gap in the validation.",
}


@dataclass(frozen=True)
class Requirement:
    """One supervisory reference, and what would evidence it here."""

    reference: str
    title: str
    #: What the reference asks for, in the engine's own words.
    asks_for: str
    #: Whether the evidence is a measurement or a record.
    kind: str

    def tests(self) -> tuple[str, ...]:
        """The tests that name this reference. Read, never restated."""
        return tuple(t.test_id for t in test_registry.TESTS
                     if self.reference in t.cbuae)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference, "title": self.title,
            "asks_for": self.asks_for, "kind": self.kind,
            "framework": FRAMEWORK,
            "evidenced_by": list(self.tests()),
            "summary_is_a_reading_aid": SUMMARIES_ARE_A_READING_AID,
        }


QUANTITATIVE = "QUANTITATIVE"
DOCUMENTARY = "DOCUMENTARY"

REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "MMS 4.9", "Model documentation",
        "That the development, assumptions, limitations and intended use of "
        "a model are documented well enough that a competent reviewer who "
        "was not involved in building it can follow what was done and why.",
        DOCUMENTARY),
    Requirement(
        "MMS 9.4", "Ongoing monitoring",
        "That a model in use is monitored between validations, on measures "
        "that would detect deterioration before an annual cycle would, and "
        "that the monitoring has thresholds attached to it rather than being "
        "a chart somebody looks at.",
        QUANTITATIVE),
    Requirement(
        "MMS 10.3", "Conceptual soundness",
        "That the model's purpose, its target definition, its observation "
        "and performance windows and its sign conventions are recorded and "
        "internally consistent, before any question about how well it "
        "performs.",
        DOCUMENTARY),
    Requirement(
        "MMS 10.4", "Outcomes analysis",
        "That the model's realised performance is measured against its "
        "predictions on data with a closed outcome window — discrimination, "
        "calibration, stability, the behaviour of individual "
        "characteristics, and whether the production implementation is the "
        "approved one.",
        QUANTITATIVE),
    Requirement(
        "MMG 2.8", "Model purpose and design",
        "That the model was designed for the use it is being put to, and "
        "that the design choices are recorded rather than inferred from the "
        "code.",
        DOCUMENTARY),
    Requirement(
        "MMG 2.9", "Use test",
        "That the model is used the way its approval describes — including "
        "at the cut-off, where a policy that is routinely departed from is "
        "not the policy in force.",
        QUANTITATIVE),
    Requirement(
        "MMG 2.10", "Overrides and departures from the model",
        "That departures from the model's output are recorded, attributed, "
        "reasoned, and measured against their outcomes.",
        QUANTITATIVE),
    Requirement(
        "MMG 2.11", "Independent validation",
        "That the validation is performed independently of development, "
        "reproduces the model's numbers rather than accepting them, and "
        "states what it could not test.",
        QUANTITATIVE),
    Requirement(
        "MMG 3.9", "Calibration and probability estimates",
        "That where a model produces probabilities rather than only an "
        "ordering, those probabilities are compared against realised "
        "outcomes at the level decisions are taken.",
        QUANTITATIVE),
)

BY_REFERENCE: dict[str, Requirement] = {r.reference: r for r in REQUIREMENTS}


def _status(mapped: tuple[str, ...],
            found: dict[str, states.Result]) -> str:
    ran = [t for t in mapped if t in found]
    if not ran:
        return NOT_EVIDENCED
    measured = [t for t in ran if found[t].measured]
    inapplicable = [t for t in ran
                    if found[t].state == states.NOT_APPLICABLE]
    if len(inapplicable) == len(ran):
        return NOT_APPLICABLE
    if not measured:
        return NOT_EVIDENCED
    # Inapplicable tests do not count against coverage: a model with no
    # challenger has no champion-challenger evidence to be missing.
    expected = [t for t in ran if t not in inapplicable]
    return EVIDENCED if len(measured) == len(expected) else PARTIALLY_EVIDENCED


def coverage(results: list[states.Result]) -> dict[str, Any]:
    """Which references this run evidences, and precisely where it did not.

    The gaps are the useful half. A reference reported as PARTIALLY EVIDENCED
    with a list of which tests refused and why is something a validator can
    act on; the same reference reported as a percentage is not.
    """
    found = {r.test_id: r for r in results}
    rows: list[dict[str, Any]] = []
    for requirement in REQUIREMENTS:
        mapped = requirement.tests()
        ran = [t for t in mapped if t in found]
        measured = [t for t in ran if found[t].measured]
        refused = [
            {"test_id": t, "state": found[t].state,
             "state_label": states.STATE_LABELS[found[t].state],
             "why": found[t].detail}
            for t in ran if not found[t].measured]
        adverse = [t for t in measured if found[t].adverse]
        rows.append({
            **requirement.to_dict(),
            "status": _status(mapped, found),
            "mapped_tests": len(mapped),
            "tests_run": len(ran),
            "tests_measured": len(measured),
            "measured_test_ids": measured,
            "not_measured": refused,
            "adverse_test_ids": adverse,
            "not_run": [t for t in mapped if t not in found],
        })

    tally = dict.fromkeys(STATUSES, 0)
    for row in rows:
        tally[row["status"]] += 1
    return {
        "regulatory_version": REGULATORY_VERSION,
        "framework": FRAMEWORK,
        "disclaimer": DISCLAIMER,
        "this_is_not_a_compliance_assessment": True,
        "summary_is_a_reading_aid": SUMMARIES_ARE_A_READING_AID,
        "status_meaning": STATUS_MEANING,
        "requirements": rows,
        "by_status": tally,
        "references": len(REQUIREMENTS),
    }


def catalogue() -> dict[str, Any]:
    """The map itself, with nothing run. What a reader can inspect first."""
    return {
        "regulatory_version": REGULATORY_VERSION,
        "framework": FRAMEWORK,
        "disclaimer": DISCLAIMER,
        "this_is_not_a_compliance_assessment": True,
        "summary_is_a_reading_aid": SUMMARIES_ARE_A_READING_AID,
        "requirements": [r.to_dict() for r in REQUIREMENTS],
        "unmapped_tests": [
            t.test_id for t in test_registry.TESTS
            if not set(t.cbuae) & set(BY_REFERENCE)
        ],
    }


__all__ = [
    "BY_REFERENCE", "DISCLAIMER", "DOCUMENTARY", "EVIDENCED", "FRAMEWORK",
    "NOT_APPLICABLE", "NOT_EVIDENCED", "PARTIALLY_EVIDENCED", "QUANTITATIVE",
    "REGULATORY_VERSION", "REQUIREMENTS", "STATUSES", "STATUS_MEANING",
    "Requirement", "catalogue", "coverage",
]
