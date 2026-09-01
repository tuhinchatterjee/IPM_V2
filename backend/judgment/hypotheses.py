"""
Hypothesis trees and the mandatory challenge pass. §70, §71.

Why an investigation needs hypotheses at all
---------------------------------------------
Without them an investigation is a list of analyses, and a list of analyses
produces a list of findings, and a list of findings is not an answer. The
question "what is going on in Contracting?" has candidate answers — exposure
grew, credit quality fell, two names blew up, the join changed — and the work
is deciding which of them the evidence supports.

Naming them up front does two things a summary at the end cannot. It makes the
analysis that would DISTINGUISH between two explanations obvious, and it makes
an untested explanation visible. An investigation that never considered "the
denominator changed" and an investigation that considered and dismissed it read
identically in a findings list, and they are not the same investigation.

Status comes from evidence, never from a model
------------------------------------------------
    "confidence is not LLM self-confidence. Use evidence coverage and
     validation state."

So a hypothesis is SUPPORTED because the analyses it named ran and pointed one
way, and UNRESOLVED because they did not run. A model may write the sentence
that explains it. It cannot choose the word.

NOT_TESTABLE is the honest fifth status, and the one most likely to be missing:
"the change is temporary rather than persistent" is not testable on two periods
of history, and recording that is better than recording UNRESOLVED, which
implies somebody could resolve it by trying harder.

The challenge pass
------------------
§71's fourteen questions are the ones a good analyst asks their own conclusion
before saying it out loud. Every one of them has ended a credit narrative at
some point. They run before a material conclusion is final, their results are
persisted, and — the part that makes it real — the final answer states the
material ones that are still unresolved.

A challenge that was skipped is not a challenge that passed. That sentence is
the same one Phase 0's Trace work turned on, and it recurs here because it is
the same failure: an unrun check reported as clear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.judgment import materiality as mt

HYPOTHESIS_VERSION = "1.0.0"

# ---------------------------------------------------------- §70's statuses
SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
CONTRADICTED = "CONTRADICTED"
UNRESOLVED = "UNRESOLVED"
#: The honest fifth, and the one most likely to be missing. "The change is
#: temporary rather than persistent" is not testable on two periods, and
#: recording UNRESOLVED implies somebody could resolve it by trying harder.
NOT_TESTABLE = "NOT_TESTABLE"

STATUSES: tuple[str, ...] = (SUPPORTED, PARTIALLY_SUPPORTED, CONTRADICTED,
                             UNRESOLVED, NOT_TESTABLE)

#: Statuses that mean the hypothesis was actually examined. UNRESOLVED is not
#: one: an investigation whose hypotheses are all unresolved has produced a
#: list of questions, not an answer.
SETTLED: frozenset[str] = frozenset({SUPPORTED, PARTIALLY_SUPPORTED,
                                     CONTRADICTED, NOT_TESTABLE})


@dataclass
class Hypothesis:
    """One candidate explanation. §70."""

    hypothesis_id: str
    statement: str
    #: What would have to be true. Named before the analysis runs, so the
    #: analysis is chosen to answer the question rather than the question
    #: rewritten to fit the analysis.
    required_evidence: list[str] = field(default_factory=list)
    planned_analysis: list[str] = field(default_factory=list)
    #: Fact ids the evidence graph holds for it.
    result_references: list[str] = field(default_factory=list)
    status: str = UNRESOLVED
    #: Why it ended where it did. Written by whatever settled it.
    reason: str = ""
    #: Computed from evidence coverage and validation state. Never supplied.
    confidence: float = 0.0

    @property
    def settled(self) -> bool:
        return self.status in SETTLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "statement": self.statement,
            "required_evidence": list(self.required_evidence),
            "planned_analysis": list(self.planned_analysis),
            "result_references": list(self.result_references),
            "status": self.status, "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "settled": self.settled,
        }


def confidence(hypothesis: Hypothesis, *, validated: int,
               cited: int) -> float:
    """§70's rule: evidence coverage and validation state, nothing else.

    Two factors. How much of the evidence the hypothesis said it needed
    actually exists, and how much of what exists was validated. A hypothesis
    that named four pieces of evidence and got one validated piece lands low,
    which is the number a reader should see — and is a number no model was
    asked for.
    """
    wanted = len(hypothesis.required_evidence) or 1
    coverage = min(1.0, cited / wanted)
    quality = (validated / cited) if cited else 0.0
    return round(coverage * quality, 3)


@dataclass
class Tree:
    """The hypotheses one investigation is testing. §70."""

    observed_issue: str = ""
    hypotheses: list[Hypothesis] = field(default_factory=list)

    def add(self, hypothesis: Hypothesis) -> Hypothesis:
        self.hypotheses.append(hypothesis)
        return hypothesis

    def get(self, hypothesis_id: str) -> Hypothesis | None:
        return next((h for h in self.hypotheses
                     if h.hypothesis_id == hypothesis_id), None)

    def settle(self, hypothesis_id: str, status: str, *, reason: str,
               facts: list[str] | None = None, validated: int = 0) -> None:
        """Record what the evidence said.

        `validated` is passed in rather than derived here because the evidence
        graph is the authority on validation state and a second opinion about
        it is a second source of truth.
        """
        if status not in STATUSES:
            raise ValueError(f"{status!r} is not a hypothesis status")
        found = self.get(hypothesis_id)
        if found is None:
            raise KeyError(hypothesis_id)
        found.status = status
        found.reason = reason
        if facts is not None:
            found.result_references = list(facts)
        found.confidence = confidence(found, validated=validated,
                                      cited=len(found.result_references))

    @property
    def unresolved(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.status == UNRESOLVED]

    @property
    def supported(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses
                if h.status in (SUPPORTED, PARTIALLY_SUPPORTED)]

    @property
    def complete(self) -> bool:
        """Whether the tree has been worked rather than merely written.

        An investigation whose hypotheses are all UNRESOLVED has produced a
        list of questions. That is a legitimate intermediate state and an
        illegitimate final one.
        """
        return bool(self.hypotheses) and not self.unresolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": HYPOTHESIS_VERSION,
            "observed_issue": self.observed_issue,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "complete": self.complete,
            "unresolved": [h.hypothesis_id for h in self.unresolved],
            "supported": [h.hypothesis_id for h in self.supported],
        }


#: §70's own example, and the standard set for a deterioration investigation.
#: Six, and the sixth is the one investigations skip: "the movement is an
#: artefact" is unglamorous and correct often enough to be worth naming every
#: time.
STANDARD: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("H1", "Exposure growth or portfolio mix explains the movement.",
     ("exposure movement", "mix effect")),
    ("H2", "Underlying credit quality deteriorated.",
     ("rating or stage movement", "parameter movement")),
    ("H3", "The result is concentrated in a few borrowers.",
     ("contribution distribution", "top-n share")),
    ("H4", "The result is broad across the segment.",
     ("participation rate", "affected entity count")),
    ("H5", "The change is temporary rather than persistent.",
     ("history of at least four periods", "persistence verdict")),
    ("H6", "Data, joins, periods or denominator changes explain the apparent "
           "movement.",
     ("period alignment", "population reconciliation", "join integrity")),
)


def standard_tree(observed_issue: str) -> Tree:
    """The six hypotheses a deterioration investigation starts from."""
    tree = Tree(observed_issue=observed_issue)
    for hid, statement, evidence in STANDARD:
        tree.add(Hypothesis(hypothesis_id=hid, statement=statement,
                            required_evidence=list(evidence)))
    return tree


# ---------------------------------------------------------------------------
# §71 — the mandatory challenge pass
# ---------------------------------------------------------------------------

PASSED = "PASSED"
#: The challenge found something. Not a failure of the investigation — it is
#: the investigation working — but a finding the answer has to carry.
RAISED = "RAISED"
#: It could not be run. Distinct from PASSED for the same reason a skipped
#: validation is distinct from a passing one.
NOT_RUN = "NOT_RUN"
NOT_APPLICABLE = "NOT_APPLICABLE"

OUTCOMES: tuple[str, ...] = (PASSED, RAISED, NOT_RUN, NOT_APPLICABLE)


@dataclass(frozen=True)
class Challenge:
    """One of §71's questions."""

    id: str
    question: str
    #: What it would take to answer it. Named so NOT_RUN can say why.
    needs: str = ""
    #: A challenge that comes back RAISED and unresolved on a material
    #: conclusion must appear in the answer. Not all of them do — a data
    #: quality note on an immaterial finding is noise.
    material: bool = True


CHALLENGES: tuple[Challenge, ...] = (
    Challenge("largest_borrower",
              "Is one large borrower driving the result?",
              "a contribution decomposition"),
    Challenge("population_change",
              "Did the population change between the two dates?",
              "the matched population"),
    Challenge("new_exited",
              "Did new or exited customers drive the movement?",
              "the population effect"),
    Challenge("denominator",
              "Did the denominator change?",
              "the denominator at both dates"),
    Challenge("one_period_noise",
              "Is the finding one-period noise?",
              "at least four periods of history"),
    Challenge("persistent",
              "Is it persistent?",
              "the persistence verdict"),
    Challenge("period_alignment",
              "Are the two periods aligned?",
              "the period contract"),
    Challenge("grain_alignment",
              "Is the grain aligned on both sides?",
              "the grain contract"),
    Challenge("join_integrity",
              "Did a join multiply or lose rows?",
              "row counts before and after each join"),
    Challenge("hidden_offsets",
              "Are favourable offsets hidden inside the net movement?",
              "the gross adverse and favourable movement"),
    Challenge("overlay_effect",
              "Did an overlay or override drive the ECL?",
              "model ECL against final ECL"),
    Challenge("data_quality",
              "Is data quality sufficient for the claim?",
              "coverage and completeness of the datasets used",
              material=False),
    Challenge("alternative_conclusion",
              "Is there a plausible alternative conclusion?",
              "the hypothesis tree"),
    Challenge("second_method",
              "Does a second method support the first conclusion?",
              "a second governed method over the same population",
              material=False),
)

BY_ID: dict[str, Challenge] = {c.id: c for c in CHALLENGES}


@dataclass
class Finding:
    """What one challenge found."""

    challenge_id: str
    outcome: str = NOT_RUN
    #: What it found, or why it could not run. Never empty for RAISED or
    #: NOT_RUN — an unexplained "raised" is an alarm with no information.
    detail: str = ""
    fact_ids: list[str] = field(default_factory=list)
    #: Set when somebody or something resolved a raised challenge.
    resolved: bool = False
    resolution: str = ""

    @property
    def challenge(self) -> Challenge | None:
        return BY_ID.get(self.challenge_id)

    @property
    def outstanding(self) -> bool:
        """Whether the answer has to carry this.

        RAISED and unresolved, or NOT_RUN on a material challenge. The second
        is the one people forget: a challenge that could not be run has not
        cleared the conclusion, and reporting it as though it had is the same
        failure as a skipped validation shown as passed.
        """
        if self.outcome == RAISED:
            return not self.resolved
        if self.outcome == NOT_RUN:
            return bool(self.challenge and self.challenge.material)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "question": self.challenge.question if self.challenge else "",
            "outcome": self.outcome, "detail": self.detail,
            "fact_ids": list(self.fact_ids), "resolved": self.resolved,
            "resolution": self.resolution, "outstanding": self.outstanding,
        }


@dataclass
class Pass:
    """A whole challenge pass, and whether the conclusion survived it."""

    conclusion: str = ""
    materiality: str = mt.MODERATE
    findings: list[Finding] = field(default_factory=list)

    def record(self, challenge_id: str, outcome: str, *, detail: str = "",
               facts: list[str] | None = None) -> Finding:
        if challenge_id not in BY_ID:
            raise KeyError(f"{challenge_id!r} is not one of §71's challenges")
        if outcome not in OUTCOMES:
            raise ValueError(f"{outcome!r} is not a challenge outcome")
        if outcome in (RAISED, NOT_RUN) and not detail:
            raise ValueError(
                "a raised or unrun challenge must say what it found or why it "
                "could not run; an unexplained one is an alarm with no "
                "information")
        found = Finding(challenge_id=challenge_id, outcome=outcome,
                        detail=detail, fact_ids=list(facts or []))
        self.findings.append(found)
        return found

    def resolve(self, challenge_id: str, resolution: str) -> None:
        for finding in self.findings:
            if finding.challenge_id == challenge_id:
                finding.resolved = True
                finding.resolution = resolution

    @property
    def run(self) -> set[str]:
        return {f.challenge_id for f in self.findings
                if f.outcome != NOT_RUN}

    @property
    def outstanding(self) -> list[Finding]:
        """What the answer must state. §71's last sentence."""
        recorded = {f.challenge_id for f in self.findings}
        missing = [Finding(challenge_id=c.id, outcome=NOT_RUN,
                           detail="this challenge was not attempted")
                   for c in CHALLENGES if c.id not in recorded]
        return [f for f in [*self.findings, *missing] if f.outstanding]

    @property
    def complete(self) -> bool:
        """Whether every material challenge was actually attempted.

        A challenge that was skipped is not a challenge that passed — the same
        sentence Phase 0's Trace work turned on, recurring because it is the
        same failure.
        """
        return all(c.id in self.run for c in CHALLENGES if c.material)

    @property
    def survives(self) -> bool:
        """Whether the conclusion may be stated without qualification.

        A material conclusion with an outstanding challenge may still be
        stated — §71 says the answer must STATE the unresolved challenges, not
        suppress the conclusion — but it may not be stated flatly, and this is
        what the presentation layer reads to know that.
        """
        return not self.outstanding

    def sentence(self) -> str:
        """What the answer says about its own challenges."""
        outstanding = self.outstanding
        if not outstanding:
            return (f"All {len(CHALLENGES)} challenges to this conclusion "
                    "were run and none was left open.")
        raised = [f for f in outstanding if f.outcome == RAISED]
        unrun = [f for f in outstanding if f.outcome == NOT_RUN]
        parts: list[str] = []
        if raised:
            parts.append("; ".join(
                f"{(f.challenge.question if f.challenge else f.challenge_id)} "
                f"— {f.detail}" for f in raised))
        if unrun:
            parts.append(
                f"{len(unrun)} material challenge(s) could not be run: "
                + ", ".join(f.challenge_id for f in unrun))
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": HYPOTHESIS_VERSION,
            "conclusion": self.conclusion,
            "materiality": self.materiality,
            "findings": [f.to_dict() for f in self.findings],
            "outstanding": [f.to_dict() for f in self.outstanding],
            "complete": self.complete,
            "survives": self.survives,
            "sentence": self.sentence(),
            "run": sorted(self.run),
            "not_run": sorted(c.id for c in CHALLENGES
                              if c.id not in self.run),
        }


def required_for(materiality_band: str) -> list[Challenge]:
    """Which challenges a conclusion of this materiality must face.

    Everything material, always. The two non-material ones — data quality and
    second-method corroboration — are required only for HIGH and CRITICAL,
    because running them on every immaterial observation buries the ones that
    matter under fourteen paragraphs of clearance.
    """
    if materiality_band in (mt.HIGH, mt.CRITICAL):
        return list(CHALLENGES)
    return [c for c in CHALLENGES if c.material]


__all__ = ["BY_ID", "CHALLENGES", "CONTRADICTED", "Challenge", "Finding",
           "HYPOTHESIS_VERSION", "Hypothesis", "NOT_APPLICABLE",
           "NOT_RUN", "NOT_TESTABLE", "OUTCOMES", "PARTIALLY_SUPPORTED",
           "PASSED", "Pass", "RAISED", "SETTLED", "STANDARD", "STATUSES",
           "SUPPORTED", "Tree", "UNRESOLVED", "confidence", "required_for",
           "standard_tree"]
