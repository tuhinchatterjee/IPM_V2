"""
A Candidate Learning Case: what a user's correction becomes. §14, §15.

The pipeline this sits in the middle of
-----------------------------------------
    FEEDBACK EVENT → ERROR CLASSIFICATION → CANDIDATE LEARNING CASE →
    REDACTION → PROPOSED CORRECTION → DETERMINISTIC VALIDATION →
    HUMAN REVIEW → CURRICULUM → REPLAY → SEALED HOLDOUT →
    CANDIDATE RELEASE → APPROVAL → PRODUCTION → MONITORING/ROLLBACK

Fourteen transitions between a user saying "that's wrong" and the product
behaving differently. That is not bureaucracy: it is the difference between a
system that learns and a system that agrees with whoever complained most
recently.

What a candidate is NOT
-------------------------
It is not the user's correction. §8 is explicit — "do not treat a user
correction as automatically correct" — and this object keeps the two apart in
its own field names: `user_correction` is what they said, `proposed_*` is what
review would put in its place, and nothing copies the first into the second
without a person.

The nine statuses
------------------
DRAFT, AUTO_PROPOSED, NEEDS_REVIEW, SYSTEM_REFERENCE_VALIDATED,
HUMAN_REVIEWED, HUMAN_APPROVED, REJECTED, RETIRED, APPLIED_TO_RELEASE.

SYSTEM_REFERENCE_VALIDATED and HUMAN_REVIEWED are separate from HUMAN_APPROVED
for the reason the teaching library keeps them separate: a deterministic check
passing is not a person agreeing, and a person having read it is not a person
signing for it. Collapsing any pair of those three is how an auto-validated
case ends up in production wearing an approval nobody gave.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

CANDIDATE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# §15's nine statuses
# ---------------------------------------------------------------------------

DRAFT = "DRAFT"
AUTO_PROPOSED = "AUTO_PROPOSED"
NEEDS_REVIEW = "NEEDS_REVIEW"
SYSTEM_REFERENCE_VALIDATED = "SYSTEM_REFERENCE_VALIDATED"
HUMAN_REVIEWED = "HUMAN_REVIEWED"
HUMAN_APPROVED = "HUMAN_APPROVED"
REJECTED = "REJECTED"
RETIRED = "RETIRED"
APPLIED_TO_RELEASE = "APPLIED_TO_RELEASE"

STATUSES: tuple[str, ...] = (
    DRAFT, AUTO_PROPOSED, NEEDS_REVIEW, SYSTEM_REFERENCE_VALIDATED,
    HUMAN_REVIEWED, HUMAN_APPROVED, REJECTED, RETIRED, APPLIED_TO_RELEASE)

STATUS_MEANS: dict[str, str] = {
    DRAFT: "Being written. Not yet proposed to anybody.",
    AUTO_PROPOSED: "The pipeline made it from a feedback event. Nobody has "
                   "looked.",
    NEEDS_REVIEW: "Queued for a human reviewer.",
    SYSTEM_REFERENCE_VALIDATED: "A deterministic check agrees with the "
                                "proposed answer. That is not a person "
                                "agreeing.",
    HUMAN_REVIEWED: "A person read it and did not sign for it. The state that "
                    "exists to be distinguished FROM approval.",
    HUMAN_APPROVED: "A named person signed for it. Only this status may enter "
                    "a Learning Release.",
    REJECTED: "Not a valid lesson. The reason is kept.",
    RETIRED: "Was valid and no longer applies. Terminal.",
    APPLIED_TO_RELEASE: "Included in a Learning Release that has been built.",
}

#: What may follow what. RETIRED and APPLIED_TO_RELEASE are terminal.
TRANSITIONS: dict[str, frozenset[str]] = {
    DRAFT: frozenset({AUTO_PROPOSED, NEEDS_REVIEW, REJECTED}),
    AUTO_PROPOSED: frozenset({NEEDS_REVIEW, SYSTEM_REFERENCE_VALIDATED,
                              REJECTED}),
    NEEDS_REVIEW: frozenset({SYSTEM_REFERENCE_VALIDATED, HUMAN_REVIEWED,
                             HUMAN_APPROVED, REJECTED}),
    SYSTEM_REFERENCE_VALIDATED: frozenset({HUMAN_REVIEWED, HUMAN_APPROVED,
                                           REJECTED}),
    HUMAN_REVIEWED: frozenset({HUMAN_APPROVED, REJECTED, NEEDS_REVIEW}),
    HUMAN_APPROVED: frozenset({APPLIED_TO_RELEASE, RETIRED, REJECTED}),
    REJECTED: frozenset({NEEDS_REVIEW}),
    RETIRED: frozenset(),
    APPLIED_TO_RELEASE: frozenset({RETIRED}),
}

#: The only status a Learning Release may contain.
RELEASABLE: frozenset[str] = frozenset({HUMAN_APPROVED})


def may_move(current: str, to: str) -> bool:
    """Fail-closed: an unknown status permits nothing."""
    return to in TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Failure classes
# ---------------------------------------------------------------------------

#: What went wrong, in the terms the pipeline can act on. Derived from the
#: user's issue categories rather than asked for separately: a user reports
#: symptoms, and the class is what a reviewer needs.
CLASSES: dict[str, str] = {
    "reading": "CreditProbe read the question as a different question.",
    "selection": "It chose the wrong officer, agents, dataset or method.",
    "scope": "Wrong period, population or grain.",
    "structure": "Wrong join, or rows multiplied by one.",
    "computation": "The arithmetic or the method itself.",
    "presentation": "Right figures, wrong form or wrong length.",
    "judgment": "Right figures, wrong thing said about them.",
    "regulatory": "A source, a citation, an effective date or an exception.",
    "product": "A defect in the software rather than in the analysis.",
    "unclassified": "Nothing in the report says which part failed.",
}

#: issue category -> failure class.
_CLASS_OF: dict[str, str] = {
    "wrong_intent": "reading",
    "wrong_officer": "selection",
    "wrong_dataset": "selection",
    "wrong_field": "selection",
    "wrong_exposure": "selection",
    "wrong_method": "selection",
    "wrong_period": "scope",
    "wrong_population": "scope",
    "wrong_grain": "scope",
    "wrong_join": "structure",
    "wrong_calculation": "computation",
    "wrong_result": "computation",
    "wrong_interpretation": "judgment",
    "unsupported_claim": "judgment",
    "incomplete": "judgment",
    "missed_exception": "regulatory",
    "regulatory_source": "regulatory",
    "wrong_visual": "presentation",
    "too_much_detail": "presentation",
    "too_little_detail": "presentation",
    "broken_navigation": "product",
    "slow": "product",
    "other": "unclassified",
}


def classify(categories: list[str]) -> str:
    """The failure class a set of reported categories implies.

    Earliest-in-the-pipeline wins. A user who ticks "wrong period" and "wrong
    result" has reported one failure and its consequence, and routing it as a
    computation error sends a reviewer to check arithmetic that is correct.
    """
    order = ["reading", "selection", "scope", "structure", "computation",
             "judgment", "regulatory", "presentation", "product",
             "unclassified"]
    found = {_CLASS_OF.get(c, "unclassified") for c in categories}
    for name in order:
        if name in found:
            return name
    return "unclassified"


# ---------------------------------------------------------------------------
# The candidate
# ---------------------------------------------------------------------------


@dataclass
class CandidateCase:
    """§15's object. What was, what the user says, what review proposes."""

    candidate_id: str = field(
        default_factory=lambda: f"cand-{uuid.uuid4().hex[:14]}")
    tenant: str = ""
    status: str = DRAFT

    # ---- where it came from
    feedback_event_id: str = ""
    observation_id: str = ""
    question: str = ""
    thread: list[str] = field(default_factory=list)

    # ---- what happened
    original_reading: dict[str, Any] = field(default_factory=dict)
    original_officer: int | None = None
    original_agents: list[str] = field(default_factory=list)
    original_plan: dict[str, Any] = field(default_factory=dict)
    original_result: dict[str, Any] = field(default_factory=dict)
    failure_class: str = "unclassified"

    # ---- what the user said. Never treated as true.
    user_correction: dict[str, Any] = field(default_factory=dict)

    # ---- what review proposes instead. Never copied from the user.
    proposed_reading: dict[str, Any] = field(default_factory=dict)
    proposed_officer: int | None = None
    proposed_agents: list[str] = field(default_factory=list)
    proposed_plan: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    required_datasets: list[str] = field(default_factory=list)
    required_methods: list[str] = field(default_factory=list)
    required_invariants: list[str] = field(default_factory=list)
    answer_contract: dict[str, Any] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)

    # ---- governance
    reviewer: str = ""
    review_note: str = ""
    rejected_because: str = ""
    redacted: bool = False
    redaction_note: str = ""
    release_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = CANDIDATE_VERSION

    @property
    def releasable(self) -> bool:
        return self.status in RELEASABLE

    @property
    def has_proposal(self) -> bool:
        """Whether review has said what SHOULD have happened.

        A candidate with no proposal is a complaint with a status. It can be
        reviewed and rejected; it cannot be approved, because there is nothing
        to approve.
        """
        return bool(self.proposed_reading or self.proposed_plan
                    or self.proposed_officer is not None
                    or self.proposed_agents or self.expected_outcome)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "tenant": self.tenant,
            "status": self.status,
            "status_means": STATUS_MEANS.get(self.status, ""),
            "feedback_event_id": self.feedback_event_id,
            "observation_id": self.observation_id,
            "question": self.question, "thread": list(self.thread),
            "original": {
                "reading": dict(self.original_reading),
                "officer": self.original_officer,
                "agents": list(self.original_agents),
                "plan": dict(self.original_plan),
                "result": dict(self.original_result)},
            "failure_class": self.failure_class,
            "failure_means": CLASSES.get(self.failure_class, ""),
            "user_correction": dict(self.user_correction),
            "proposed": {
                "reading": dict(self.proposed_reading),
                "officer": self.proposed_officer,
                "agents": list(self.proposed_agents),
                "plan": dict(self.proposed_plan),
                "outcome": self.expected_outcome,
                "datasets": list(self.required_datasets),
                "methods": list(self.required_methods),
                "invariants": list(self.required_invariants),
                "answer_contract": dict(self.answer_contract),
                "citations": list(self.citations)},
            "reviewer": self.reviewer, "review_note": self.review_note,
            "rejected_because": self.rejected_because,
            "redacted": self.redacted, "redaction_note": self.redaction_note,
            "release_id": self.release_id,
            "releasable": self.releasable,
            "has_proposal": self.has_proposal,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "schema_version": self.schema_version,
        }


class CandidateError(Exception):
    """A transition or a proposal that must not happen."""


def propose(event: Any, observation: Any = None) -> CandidateCase:
    """One feedback event as an AUTO_PROPOSED candidate.

    Refuses three things, each for a different reason.

    A rating that is not PARTLY or NO carries no claim that anything was
    wrong. A YES is not a lesson.

    Feedback without consent may be a satisfaction signal and a bug report and
    may not become a learning candidate. §29.

    And feedback about an answer nobody can reproduce cannot be validated
    against anything, so approving it would mean approving a change on the
    strength of one person's recollection.
    """
    from backend.learning import feedback as fb

    rating = str(getattr(event, "rating", "") or "")
    if rating not in fb.WANTS_DETAIL:
        raise CandidateError(
            f"a {rating} carries no claim that anything was wrong; a "
            "candidate learning case needs one")
    if not fb.may_learn_from(str(getattr(event, "consent", ""))):
        raise CandidateError(
            "this feedback was given without consent to improve the bank's "
            "CreditProbe. It counts as a satisfaction signal and as a bug "
            "report, and it may not become a learning candidate.")
    if not getattr(event, "reproducible", False):
        raise CandidateError(
            "the answer this is about cannot be reproduced — no build, no "
            "plan and no agentic run were recorded — so there is nothing a "
            "reviewer could replay or validate against")

    correction = getattr(event, "correction", None)
    return CandidateCase(
        tenant=str(getattr(event, "tenant", "") or ""),
        status=AUTO_PROPOSED,
        feedback_event_id=str(getattr(event, "event_id", "") or ""),
        observation_id=str(getattr(observation, "observation_id", "") or ""),
        question=str(getattr(event, "question", "") or ""),
        original_reading=dict(getattr(observation, "reading", None) or {}),
        original_officer=getattr(event, "officer_level", None),
        original_agents=[str(a) for a in (getattr(event, "agents", None)
                                          or [])],
        original_plan=dict(getattr(observation, "plan", None) or {}),
        original_result=dict(getattr(observation, "result", None) or {}),
        failure_class=classify(list(getattr(event, "categories", None) or [])),
        # What they SAID. Nothing copies it into `proposed_*`.
        user_correction=(correction.to_dict() if correction is not None
                         else {}),
    )


def move(case: CandidateCase, to: str, *, reviewer: str = "",
         note: str = "") -> CandidateCase:
    """Move a candidate, or refuse and say why.

    Three refusals worth stating:

    An approval needs a named reviewer AND a proposal. "Approved" on a case
    that says only what went wrong approves nothing and looks like progress.

    A rejection needs a reason, because a rejected candidate is the record of
    a decision and an unexplained one cannot be revisited.

    And a status that is not reachable from the current one is refused rather
    than set, because the point of the ladder is that it cannot be skipped.
    """
    if to not in STATUSES:
        raise CandidateError(f"{to!r} is not a candidate status")
    if not may_move(case.status, to):
        allowed = ", ".join(sorted(TRANSITIONS.get(case.status, frozenset())))
        raise CandidateError(
            f"a {case.status} candidate cannot become {to}"
            + (f"; it may become {allowed}" if allowed
               else " — that status is terminal"))
    if to in (HUMAN_REVIEWED, HUMAN_APPROVED) and not str(reviewer).strip():
        raise CandidateError(f"{to} needs a named reviewer")
    if to == HUMAN_APPROVED and not case.has_proposal:
        raise CandidateError(
            "this candidate records what went wrong and not what should have "
            "happened. Approving it would approve nothing; add the proposed "
            "reading, plan or outcome first.")
    if to == HUMAN_APPROVED and not str(note).strip():
        raise CandidateError(
            "an approval needs the reviewer's reason: a signature with no "
            "assessment is indistinguishable from nobody having looked")
    if to == REJECTED and not str(note).strip():
        raise CandidateError(
            "a rejection needs a reason, so the decision can be revisited")

    case.status = to
    case.updated_at = datetime.now(UTC)
    if reviewer:
        case.reviewer = str(reviewer).strip()
    if note:
        if to == REJECTED:
            case.rejected_because = note
        else:
            case.review_note = note
    return case


__all__ = ["APPLIED_TO_RELEASE", "AUTO_PROPOSED", "CANDIDATE_VERSION",
           "CLASSES", "CandidateCase", "CandidateError", "DRAFT",
           "HUMAN_APPROVED", "HUMAN_REVIEWED", "NEEDS_REVIEW", "REJECTED",
           "RELEASABLE", "RETIRED", "STATUSES", "STATUS_MEANS",
           "SYSTEM_REFERENCE_VALIDATED", "TRANSITIONS", "classify",
           "may_move", "move", "propose"]
