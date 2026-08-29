"""
Component attribution, and the scores that are NOT thumbs. §153, §154, §158,
§159, §160.

    §158: "AI Intelligence Studio component validation scores must not be raw
           Good/Bad percentages."

Why that instruction is the whole module
------------------------------------------
A thumbs percentage is the easiest score in the world to compute and it
measures the wrong thing twice over. It measures who bothered to click, which
is overwhelmingly people who were annoyed. And it measures agreement, which is
not correctness — a user who wanted the answer to be smaller will mark a
correct answer BAD, and a user who did not check will mark a wrong one GOOD.

So there are two separate numbers and they never mix. RAW FEEDBACK metrics —
satisfaction, feedback rate, bad rate, reason distribution — describe what
users did. The VALIDATION SCORE describes what evaluation established, and
moves only through §160's workflow: a versioned case set changed, an approved
fix was tested, the evaluation completed, the result was tied to a release, a
reviewer approved the promotion.

Unreviewed feedback moves neither of them. It moves the raw metrics, because
that is what raw metrics are, and it moves the validation score not at all.

Automatic triage is advisory
-----------------------------
§154 is explicit: do not automatically mark the user correct or the system
wrong. `triage()` returns a SUGGESTION with a confidence and the evidence it
read, and nothing downstream may act on it without a named adjudicator. A
triage that could close its own finding is a system agreeing with itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.feedback import schema as fs
from backend.validation import intervals as iv

COMPONENT_VERSION = "1.0.0"

# ------------------------------------------------------- §159's components
INTENT = "INTENT"
COREFERENCE = "COREFERENCE"
MULTI_TURN = "MULTI_TURN_CONTEXT"
OBJECTIVE_COVERAGE = "OBJECTIVE_COVERAGE"
CONCEPTS = "CONCEPTS"
DATA = "DATA"
RELATIONSHIPS = "RELATIONSHIPS"
PERIOD_GRAIN = "PERIOD_GRAIN"
PLAN = "PLAN"
QUERY = "QUERY"
RESULT = "RESULT"
INVARIANTS = "INVARIANTS"
GROUNDING = "GROUNDING"
INTERPRETATION = "INTERPRETATION"
VISUALIZATION = "VISUALIZATION"
TRACE = "TRACE"
AGENT_SELECTION = "AGENT_SELECTION"
AGENTIC_EXECUTION = "AGENTIC_EXECUTION"
REQUIRES_ATTENTION = "REQUIRES_ATTENTION"
CONTROLLED_FAILURE = "CONTROLLED_FAILURE"

COMPONENTS: tuple[str, ...] = (
    INTENT, COREFERENCE, MULTI_TURN, OBJECTIVE_COVERAGE, CONCEPTS, DATA,
    RELATIONSHIPS, PERIOD_GRAIN, PLAN, QUERY, RESULT, INVARIANTS, GROUNDING,
    INTERPRETATION, VISUALIZATION, TRACE, AGENT_SELECTION, AGENTIC_EXECUTION,
    REQUIRES_ATTENTION, CONTROLLED_FAILURE,
)

#: Which component a user's reason POINTS AT. A suggestion, never a verdict:
#: "wrong numbers" usually means the query and sometimes means the ontology,
#: and only a person who reproduced it knows which.
SUGGESTS: dict[str, tuple[str, ...]] = {
    "misunderstood_my_question": (INTENT,),
    "missed_part_of_the_question": (OBJECTIVE_COVERAGE,),
    "wrong_population": (DATA, PERIOD_GRAIN),
    "wrong_period": (PERIOD_GRAIN,),
    "wrong_data": (DATA, CONCEPTS),
    "wrong_relationship_or_join": (RELATIONSHIPS,),
    "wrong_calculation": (PLAN, QUERY),
    "wrong_numbers": (QUERY, RESULT, INVARIANTS),
    "incomplete_answer": (OBJECTIVE_COVERAGE, INTERPRETATION),
    "weak_interpretation": (INTERPRETATION,),
    "unsupported_claim": (GROUNDING,),
    "wrong_chart": (VISUALIZATION,),
    "trace_unclear_or_inconsistent": (TRACE,),
    "too_much_information": (INTERPRETATION,),
    "not_enough_detail": (INTERPRETATION,),
    "slow": (AGENTIC_EXECUTION,),
    "error_or_failed_request": (CONTROLLED_FAILURE,),
}

# ------------------------------------------------------------ §159's states
HEALTHY = "HEALTHY"
LIMITED = "LIMITED"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
STALE = "STALE"
#: Not a grade. There is not enough evidence to grade it, which is a different
#: statement and the honest one far more often.
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

STATES: tuple[str, ...] = (HEALTHY, LIMITED, DEGRADED, FAILED, STALE,
                           INSUFFICIENT)


@dataclass
class Suggestion:
    """§154's advisory triage. Never a verdict."""

    components: list[str] = field(default_factory=list)
    failure_category: str = ""
    severity: str = "UNKNOWN"
    reproduce: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    teaching_family: str = ""
    candidate_regression: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": COMPONENT_VERSION,
            "components": list(self.components),
            "failure_category": self.failure_category,
            "severity": self.severity,
            "reproduce": list(self.reproduce),
            "related": list(self.related),
            "teaching_family": self.teaching_family,
            "candidate_regression": self.candidate_regression,
            "confidence": round(self.confidence, 3),
            "evidence": list(self.evidence),
            # Named on the payload so nothing downstream can read this as a
            # decision. A triage that could close its own finding is a system
            # agreeing with itself.
            "advisory_only": True,
            "requires_adjudication": True,
        }


def triage(feedback: fs.Feedback) -> Suggestion:
    """§154's suggestion, from deterministic evidence.

    Reads the reason codes, the failure category the runtime recorded and
    whether the item is reproducible. Never marks the user right or the
    system wrong: it says which components are worth looking at, and how
    confident that is.
    """
    found = Suggestion()
    for code in feedback.reason_codes:
        for component in SUGGESTS.get(code, ()):
            if component not in found.components:
                found.components.append(component)
                found.evidence.append(
                    f"the user chose {fs.LABELS.get(code, code)!r}")

    if feedback.failure_category:
        found.failure_category = feedback.failure_category
        found.evidence.append(
            f"the runtime recorded {feedback.failure_category}")

    found.reproduce = [
        step for step in (
            f"run {feedback.analysis_run_id}" if feedback.analysis_run_id
            else "",
            f"agentic run {feedback.agentic_run_id}"
            if feedback.agentic_run_id else "",
            f"build {feedback.build_sha}" if feedback.build_sha else "",
            f"teaching release {feedback.teaching_release_id}"
            if feedback.teaching_release_id else "")
        if step]

    # Confidence is about the EVIDENCE, not about whether the user is right.
    signals = len(found.evidence) + (1 if feedback.reproducible else 0)
    found.confidence = min(1.0, signals / 4.0)
    if feedback.reason_missing:
        found.confidence *= 0.5
        found.evidence.append(
            "no reason was given, so this is a weaker signal")

    found.severity = _severity(feedback, found)
    return found


def _severity(feedback: fs.Feedback, found: Suggestion) -> str:
    """How urgent this looks. A suggestion like everything else here."""
    if feedback.rating == fs.GOOD:
        return "NONE"
    critical = {GROUNDING, INVARIANTS, RELATIONSHIPS, PERIOD_GRAIN, RESULT}
    if set(found.components) & critical:
        return "HIGH"
    if found.components:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# §158 — two numbers that never mix
# ---------------------------------------------------------------------------

@dataclass
class RawFeedback:
    """What users did. NOT a validation score, and named so.

    Measures who bothered to click, which is overwhelmingly people who were
    annoyed — and agreement, which is not correctness. Useful for finding
    where to look; useless for saying whether something works.
    """

    answers: int = 0
    rated: int = 0
    good: int = 0
    bad: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def feedback_rate(self) -> float:
        return (self.rated / self.answers) if self.answers else 0.0

    @property
    def bad_rate(self) -> float:
        return (self.bad / self.rated) if self.rated else 0.0

    @property
    def satisfaction(self) -> float:
        return (self.good / self.rated) if self.rated else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answers": self.answers, "rated": self.rated,
            "good": self.good, "bad": self.bad,
            "feedback_rate": round(self.feedback_rate, 4),
            "bad_rate": round(self.bad_rate, 4),
            "satisfaction": round(self.satisfaction, 4),
            "reason_distribution": dict(self.reasons),
            "is_a_validation_score": False,
            "note": ("What users did, not what evaluation established. "
                     "Only a fraction of answers are rated and the fraction "
                     "is not random: people click when they are annoyed."),
        }


@dataclass
class Score:
    """§159's component score. Derived from evaluation, never from thumbs."""

    component: str
    #: Everything below comes from a versioned evaluation set.
    passed: int = 0
    total: int = 0
    critical_failures: list[str] = field(default_factory=list)
    #: Feedback that a REVIEWER adjudicated as a real failure. Counted here
    #: because an adjudicated failure is evidence; an unreviewed thumb is not.
    adjudicated_failures: int = 0
    open_regressions: int = 0
    last_evaluation: str = ""
    release: str = ""
    previous_lower: float | None = None
    stale_reasons: list[str] = field(default_factory=list)

    @property
    def rate(self) -> iv.Rate:
        return iv.rate(self.component, self.passed, self.total)

    @property
    def trend(self) -> str:
        if self.previous_lower is None or not self.total:
            return "NOT_ENOUGH_HISTORY"
        moved = self.rate.lower - self.previous_lower
        return ("IMPROVING" if moved > 2.0 else
                "DEGRADING" if moved < -2.0 else "STEADY")

    @property
    def status(self) -> str:
        """§159's six states, in order of what a reader must know first."""
        if self.stale_reasons:
            return STALE
        if self.critical_failures:
            return FAILED
        if not self.rate.reportable:
            return INSUFFICIENT
        if self.adjudicated_failures or self.open_regressions:
            return DEGRADED
        if self.rate.lower >= 90.0:
            return HEALTHY
        if self.rate.lower >= 75.0:
            return LIMITED
        return DEGRADED

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "observed": self.rate.to_dict(),
            "case_count": self.total,
            "critical_failures": list(self.critical_failures),
            "supported_lower_bound": (round(self.rate.lower, 2)
                                      if self.rate.reportable else None),
            "adjudicated_feedback_failures": self.adjudicated_failures,
            "open_regressions": self.open_regressions,
            "last_evaluation": self.last_evaluation or "never",
            "release": self.release,
            "trend": self.trend,
            "status": self.status,
            "stale_reasons": list(self.stale_reasons),
            "derived_from_thumbs": False,
            "sentence": self.sentence(),
        }

    def sentence(self) -> str:
        if self.status == INSUFFICIENT:
            return (f"{self.component}: {self.passed} of {self.total} — too "
                    "few cases to report as a rate.")
        if self.status == STALE:
            return (f"{self.component}: the evaluation describes a version "
                    "that has since changed — "
                    + ", ".join(self.stale_reasons))
        if self.critical_failures:
            return (f"{self.component}: {len(self.critical_failures)} "
                    "critical failure(s). A critical failure overrides the "
                    "average.")
        return self.rate.sentence() + (
            f" {self.adjudicated_failures} adjudicated feedback failure(s)."
            if self.adjudicated_failures else "")


# ---------------------------------------------------------------------------
# §160 — how a score is allowed to change
# ---------------------------------------------------------------------------

class NotGoverned(Exception):
    """A score change that did not go through §160's workflow.

    Raised rather than logged. A score that can drift is a score nobody can
    reason about, and the first time it drifts upward nobody will ask why.
    """


@dataclass
class Movement:
    """§160's record of one score change."""

    component: str
    previous_score: float
    new_score: float
    case_set_delta: int
    failure_delta: int
    release_delta: str
    reason: str
    reviewer: str
    at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"component": self.component,
                "previous_score": round(self.previous_score, 4),
                "new_score": round(self.new_score, 4),
                "case_set_delta": self.case_set_delta,
                "failure_delta": self.failure_delta,
                "release_delta": self.release_delta,
                "reason": self.reason, "reviewer": self.reviewer,
                "at": self.at}


def move(component: str, *, previous: Score, new: Score, reason: str,
         reviewer: str, evaluation_completed: bool,
         release: str) -> Movement:
    """§160: a score changes only under all five conditions.

    Refuses otherwise. The permissive version — record the change and note
    that it was ungoverned — produces a score history in which the governed
    and ungoverned entries look identical a month later.
    """
    if component not in COMPONENTS:
        raise KeyError(f"{component!r} is not one of §159's components")
    if not evaluation_completed:
        raise NotGoverned(
            f"{component}'s score may not move before the evaluation "
            "completes")
    if not str(reviewer).strip():
        raise NotGoverned(
            f"{component}'s score may not move without a named reviewer")
    if not str(reason).strip():
        raise NotGoverned(
            f"{component}'s score may not move without a stated reason")
    if not str(release).strip():
        raise NotGoverned(
            f"{component}'s score may not move without being tied to a "
            "release; a score with no build behind it cannot be reproduced")

    return Movement(
        component=component,
        previous_score=previous.rate.lower, new_score=new.rate.lower,
        case_set_delta=new.total - previous.total,
        failure_delta=(len(new.critical_failures)
                       - len(previous.critical_failures)),
        release_delta=release, reason=reason, reviewer=reviewer,
        at=datetime.now(UTC).isoformat(timespec="seconds"))


def promotable(feedback: fs.Feedback, *, validations_passed: bool,
               redacted: bool, has_regression: bool) -> tuple[bool, list[str]]:
    """§156: whether GOOD feedback may become a positive teaching case.

    "GOOD feedback is not automatically a gold teaching case" — the six
    conditions are all required, and the commonest one to skip is redaction,
    because a good answer about a real borrower is a good answer containing a
    real borrower.
    """
    missing: list[str] = []
    if feedback.rating != fs.GOOD:
        missing.append("this is not GOOD feedback")
    if not validations_passed:
        missing.append("the answer's own validations did not all pass")
    if not feedback.adjudicated:
        missing.append("no reviewer has approved it")
    if not redacted:
        missing.append("the entities and figures have not been redacted")
    if not has_regression:
        missing.append("no regression evidence exists for it")
    return (not missing), missing


__all__ = ["AGENTIC_EXECUTION", "AGENT_SELECTION", "COMPONENTS",
           "COMPONENT_VERSION", "CONCEPTS", "CONTROLLED_FAILURE",
           "COREFERENCE", "DATA", "DEGRADED", "FAILED", "GROUNDING",
           "HEALTHY", "INSUFFICIENT", "INTENT", "INTERPRETATION",
           "INVARIANTS", "LIMITED", "MULTI_TURN", "Movement", "NotGoverned",
           "OBJECTIVE_COVERAGE", "PERIOD_GRAIN", "PLAN", "QUERY",
           "RELATIONSHIPS", "REQUIRES_ATTENTION", "RESULT", "RawFeedback",
           "STALE", "STATES", "SUGGESTS", "Score", "Suggestion", "TRACE",
           "VISUALIZATION", "move", "promotable", "triage"]
