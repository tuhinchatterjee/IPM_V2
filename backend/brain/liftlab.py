"""Did this Brain make us better? §18, §19, §29.

The whole point of importing a Brain is that somebody else's learning helps
here. §18's design makes that a measurement rather than a hope, and three of
its rules do most of the work.

**The receiver's own cases, never the sender's.** A package that arrived with
its own evaluation set would be marking its own homework, and the score would
be high for the same reason it always is. So the comparison runs the
receiver's development cases, critical suite, sealed holdout, scope and
language cases, feedback regressions, agentic cases and assurance replays -
and §18 says in as many words: "Do not use the sender's holdout."

**A critical regression overrides a positive average.** Six dimensions
improving by two points each does not offset one new critical failure. The
average is a summary of things that are individually true; a critical failure
is a thing that is individually fatal, and averaging it away is how a release
ships with one.

**Not enough evidence is a result.** §18: "Do not claim lift from trivial
sample sizes." A candidate that improved on eleven cases has not been shown
to improve, and INSUFFICIENT_EVIDENCE is what that says. Reporting it as a
small improvement would be reporting noise with a sign.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

LIFT_LAB_VERSION = "1.0.0"

# --------------------------------------------------- the six dimensions §7

UNDERSTANDING = "Understanding & Context"
DESIGN = "Analytical Design"
COMPUTATION = "Computation & Evidence"
JUDGMENT = "Judgment & Presentation"
AGENTIC = "Agentic Delivery"
RELIABILITY = "Reliability & Experience"

DIMENSIONS: tuple[str, ...] = (
    UNDERSTANDING, DESIGN, COMPUTATION, JUDGMENT, AGENTIC, RELIABILITY,
)

# ------------------------------------------------------------- the verdicts

IMPROVEMENT = "IMPROVEMENT"
NO_MATERIAL_CHANGE = "NO MATERIAL CHANGE"
MIXED = "MIXED"
REGRESSION = "REGRESSION"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT EVIDENCE"

VERDICTS: tuple[str, ...] = (
    IMPROVEMENT, NO_MATERIAL_CHANGE, MIXED, REGRESSION,
    INSUFFICIENT_EVIDENCE,
)

# ------------------------------------------------------------- the evidence

HIGH_EVIDENCE = "HIGH EVIDENCE"
MODERATE_EVIDENCE = "MODERATE EVIDENCE"
LOW_EVIDENCE = "LOW EVIDENCE"
NO_EVIDENCE = "INSUFFICIENT EVIDENCE"

#: Below this many cases, a dimension's delta is not reported as a change.
#: 30 is where a proportion's confidence interval starts to be narrower
#: than the effects worth acting on; below it the interval is wider than
#: almost any real improvement.
MINIMUM_CASES = 30
#: Below this, nothing is claimed at all.
TRIVIAL_CASES = 12

#: A change smaller than this is noise dressed as a result.
MATERIAL_POINTS = 1.0


@dataclass
class Score:
    """One dimension on one evaluation set."""

    dimension: str
    score: float = 0.0
    cases: int = 0
    critical_failures: int = 0
    coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "score": round(self.score, 4),
                "cases": self.cases,
                "critical_failures": self.critical_failures,
                "coverage": round(self.coverage, 4)}


@dataclass
class Delta:
    """What changed on one dimension, in the three forms §61 asks for."""

    dimension: str
    baseline: Score
    candidate: Score

    @property
    def points(self) -> float:
        """Percentage-POINT change. §61 leads with this."""
        return round((self.candidate.score - self.baseline.score) * 100, 2)

    @property
    def relative(self) -> float | None:
        """Relative improvement. None where the baseline is zero.

        Returning None rather than 0 or infinity: a relative improvement on
        a baseline of nothing is not a number, and printing one would be
        inventing a denominator.
        """
        if self.baseline.score <= 0:
            return None
        return round(
            (self.candidate.score - self.baseline.score)
            / self.baseline.score * 100, 2)

    @property
    def error_reduction(self) -> float | None:
        """How much of the remaining error went away. §61's third form."""
        error = 1.0 - self.baseline.score
        if error <= 0:
            return None
        removed = self.candidate.score - self.baseline.score
        return round(removed / error * 100, 2)

    @property
    def critical_fixed(self) -> int:
        return max(0, self.baseline.critical_failures
                   - self.candidate.critical_failures)

    @property
    def critical_introduced(self) -> int:
        return max(0, self.candidate.critical_failures
                   - self.baseline.critical_failures)

    @property
    def cases(self) -> int:
        return min(self.baseline.cases, self.candidate.cases)

    @property
    def evidence(self) -> str:
        if self.cases < TRIVIAL_CASES:
            return NO_EVIDENCE
        if self.cases < MINIMUM_CASES:
            return LOW_EVIDENCE
        if self.cases < 120:
            return MODERATE_EVIDENCE
        return HIGH_EVIDENCE

    @property
    def interval(self) -> tuple[float, float] | None:
        """A 95% interval on the point change, where there is enough to say.

        A normal approximation on the difference of two proportions. Coarse,
        and stated as coarse: its job is to stop a two-point move on forty
        cases being read as a two-point move.
        """
        if self.cases < TRIVIAL_CASES:
            return None
        n = max(self.cases, 1)
        var = ((self.baseline.score * (1 - self.baseline.score))
               + (self.candidate.score * (1 - self.candidate.score))) / n
        margin = 1.96 * math.sqrt(max(var, 0.0)) * 100
        return (round(self.points - margin, 2), round(self.points + margin, 2))

    @property
    def verdict(self) -> str:
        """What may honestly be said about this dimension."""
        if self.critical_introduced:
            return REGRESSION
        if self.cases < TRIVIAL_CASES:
            return INSUFFICIENT_EVIDENCE
        if self.cases < MINIMUM_CASES and abs(self.points) < 5.0:
            # A small move on a small sample is not a result.
            return INSUFFICIENT_EVIDENCE
        band = self.interval
        if band and band[0] < 0 < band[1] and abs(self.points) < 5.0:
            return NO_MATERIAL_CHANGE
        if self.points >= MATERIAL_POINTS:
            return IMPROVEMENT
        if self.points <= -MATERIAL_POINTS:
            return REGRESSION
        return NO_MATERIAL_CHANGE

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "baseline": self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "points": self.points,
            "relative_pct": self.relative,
            "error_reduction_pct": self.error_reduction,
            "critical_fixed": self.critical_fixed,
            "critical_introduced": self.critical_introduced,
            "cases": self.cases,
            "evidence": self.evidence,
            "confidence_interval": self.interval,
            "verdict": self.verdict,
            "reads_as": self.sentence(),
        }

    def sentence(self) -> str:
        """The change, said the way §61 asks for it.

        Leads with percentage points, because "82% to 88%" described as "6%
        improvement" is ambiguous between six points and six per cent, and
        the two differ by a factor of thirteen here.
        """
        if self.verdict == INSUFFICIENT_EVIDENCE:
            return (f"{self.cases} case(s) is not enough to say whether "
                    f"{self.dimension} changed")
        direction = "+" if self.points >= 0 else ""
        parts = [f"{direction}{self.points} pp"]
        if self.relative is not None:
            parts.append(f"{direction}{self.relative}% relative")
        if self.error_reduction is not None and self.error_reduction > 0:
            parts.append(f"{self.error_reduction}% of the error removed")
        return (f"{self.dimension}: "
                f"{self.baseline.score * 100:.1f}% to "
                f"{self.candidate.score * 100:.1f}% ({', '.join(parts)}), "
                f"{self.evidence.lower()} on {self.cases} cases")


@dataclass
class LiftReport:
    """§18 and §19: what a candidate would do to this installation."""

    candidate_id: str = ""
    brain_name: str = ""
    brain_version: str = ""
    evaluation_set: str = "receiver_development"
    deltas: list[Delta] = field(default_factory=list)
    #: Sets the receiver ran. §18: never the sender's holdout.
    sets_used: tuple[str, ...] = ()
    sender_holdout_used: bool = False
    latency_delta_ms: float = 0.0
    token_delta: int = 0
    cost_delta: float = 0.0
    abstention_delta: float = 0.0
    precision_delta: float = 0.0
    coverage_gained: tuple[str, ...] = ()
    coverage_lost: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def critical_introduced(self) -> int:
        return sum(d.critical_introduced for d in self.deltas)

    @property
    def critical_fixed(self) -> int:
        return sum(d.critical_fixed for d in self.deltas)

    @property
    def verdict(self) -> str:
        """One verdict for the whole candidate.

        A critical regression is checked first and alone. Six dimensions
        improving does not offset one new critical failure: the average is a
        summary of things individually true, and a critical failure is a
        thing individually fatal.
        """
        if self.sender_holdout_used:
            return INSUFFICIENT_EVIDENCE
        if self.critical_introduced:
            return REGRESSION
        if not self.deltas:
            return INSUFFICIENT_EVIDENCE

        verdicts = [d.verdict for d in self.deltas]
        if all(v == INSUFFICIENT_EVIDENCE for v in verdicts):
            return INSUFFICIENT_EVIDENCE
        improved = sum(1 for v in verdicts if v == IMPROVEMENT)
        regressed = sum(1 for v in verdicts if v == REGRESSION)
        if regressed and improved:
            return MIXED
        if regressed:
            return REGRESSION
        if improved:
            return IMPROVEMENT
        return NO_MATERIAL_CHANGE

    def headline(self) -> str:
        if self.sender_holdout_used:
            return ("This evaluation used the sender's holdout, so it "
                    "measures nothing. §18: the receiver's own cases, "
                    "always.")
        if self.critical_introduced:
            return (f"{self.critical_introduced} critical regression(s). "
                    "This candidate may not activate, whatever the averages "
                    "say.")
        measured = [d for d in self.deltas
                    if d.verdict != INSUFFICIENT_EVIDENCE]
        if not measured:
            return ("Not enough cases to say whether this candidate helps. "
                    "That is a result, not a small improvement.")
        mean = sum(d.points for d in measured) / len(measured)
        return (f"{self.verdict}: {mean:+.2f} pp on average across "
                f"{len(measured)} measured dimension(s), "
                f"{self.critical_fixed} critical failure(s) fixed and "
                f"{self.critical_introduced} introduced.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": LIFT_LAB_VERSION,
            "candidate_id": self.candidate_id,
            "brain_name": self.brain_name,
            "brain_version": self.brain_version,
            "evaluation_set": self.evaluation_set,
            "sets_used": list(self.sets_used),
            "sender_holdout_used": self.sender_holdout_used,
            "verdict": self.verdict,
            "headline": self.headline(),
            "dimensions": [d.to_dict() for d in self.deltas],
            "critical_fixed": self.critical_fixed,
            "critical_introduced": self.critical_introduced,
            "latency_delta_ms": round(self.latency_delta_ms, 2),
            "token_delta": self.token_delta,
            "cost_delta": round(self.cost_delta, 2),
            "abstention_delta": round(self.abstention_delta, 4),
            "precision_delta": round(self.precision_delta, 4),
            "coverage_gained": list(self.coverage_gained),
            "coverage_lost": list(self.coverage_lost),
            "notes": list(self.notes),
        }


def compare(baseline: dict[str, Score], candidate: dict[str, Score], *,
            candidate_id: str = "", brain_name: str = "",
            brain_version: str = "", sets_used: tuple[str, ...] = (),
            sender_holdout_used: bool = False, **extra: Any) -> LiftReport:
    """Baseline against candidate, dimension by dimension.

    Every dimension the receiver measures appears, including ones with no
    cases. A dimension omitted because it had no evidence would read as a
    dimension that did not change.
    """
    report = LiftReport(
        candidate_id=candidate_id, brain_name=brain_name,
        brain_version=brain_version, sets_used=sets_used,
        sender_holdout_used=sender_holdout_used,
        **{k: v for k, v in extra.items()
           if k in LiftReport.__dataclass_fields__})

    for dimension in DIMENSIONS:
        before = baseline.get(dimension) or Score(dimension)
        after = candidate.get(dimension) or Score(dimension)
        report.deltas.append(Delta(dimension, before, after))

    if sender_holdout_used:
        report.notes.append(
            "The sender's holdout was used. §18 forbids it: a package "
            "evaluated on its own gold marks its own homework.")
    thin = [d.dimension for d in report.deltas
            if d.verdict == INSUFFICIENT_EVIDENCE]
    if thin:
        report.notes.append(
            "Not enough cases to judge: " + ", ".join(thin))
    return report


# ---------------------------------------------------------- §19's report


def impact_report(lift: LiftReport, *, compatibility: dict[str, Any],
                  conflicts: dict[str, Any],
                  diff: dict[str, Any]) -> dict[str, Any]:
    """§19's Brain Impact Report, in §19's order."""
    recommended, why = _recommendation(lift, conflicts)
    return {
        "executive_summary": lift.headline(),
        "compatibility": compatibility,
        "components_added": diff.get("added", []),
        "components_changed": diff.get("changed", []),
        "components_removed": diff.get("removed", []),
        "six_dimension_lift": [d.to_dict() for d in lift.deltas],
        "subcomponent_lift": diff.get("subcomponents", []),
        "critical_fixes": lift.critical_fixed,
        "critical_regressions": lift.critical_introduced,
        "new_coverage": list(lift.coverage_gained),
        "lost_coverage": list(lift.coverage_lost),
        "latency_and_cost": {
            "latency_delta_ms": round(lift.latency_delta_ms, 2),
            "token_delta": lift.token_delta,
            "cost_delta": round(lift.cost_delta, 2),
        },
        "conflicts": conflicts,
        "missing_receiver_capabilities": compatibility.get("dormant", []),
        "privacy_and_provenance": diff.get("provenance", {}),
        "recommended_decision": recommended,
        "recommendation_reason": why,
        "known_limitations": list(lift.notes),
    }


def _recommendation(lift: LiftReport,
                    conflicts: dict[str, Any]) -> tuple[str, str]:
    if lift.critical_introduced:
        return "DO NOT ACTIVATE", (
            f"{lift.critical_introduced} critical regression(s). §9 "
            "tolerates none, and a positive average does not offset one.")
    if conflicts.get("blocking"):
        return "RESOLVE CONFLICTS FIRST", (
            f"{conflicts['blocking']} conflict(s) are unsettled. Activating "
            "would run two contradictory rules at once.")
    if lift.verdict == INSUFFICIENT_EVIDENCE:
        return "GATHER MORE EVIDENCE", (
            "nothing measured moved enough, on enough cases, to say this "
            "helps. That is not a reason to refuse it; it is a reason not "
            "to claim it helped.")
    if lift.verdict == REGRESSION:
        return "DO NOT ACTIVATE", "measured performance is worse here."
    if lift.verdict == MIXED:
        return "ACTIVATE WITH REVIEW", (
            "some dimensions improved and others regressed; whether the "
            "trade is worth making is a judgement about this book.")
    if lift.verdict == IMPROVEMENT:
        return "ACTIVATE", lift.headline()
    return "ACTIVATE IF WANTED", (
        "no measured change either way. Activating is safe and buys "
        "nothing that has been shown.")
