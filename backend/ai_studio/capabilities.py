"""
Capability health, and whether CreditProbe is safe to show a client.
§103, §104.

Two honesty rules, and everything here is built around them
------------------------------------------------------------
    §103: "Do not imply statistical certainty unsupported by the sample."
    §104: "Do not display '99.99%' unless statistically demonstrated."

They are the same rule stated twice, which is a fair indication of how easily
it gets broken. A capability with eleven cases and no errors displays as 100%
and reads as solved. Its Wilson lower bound is 74%, which reads as what it is:
promising, and nowhere near demonstrated.

So a `Capability` never reports a bare percentage. Below the reporting
threshold it reports counts and says the sample is too small; above it, it
reports the interval. The score a reader sees and the score a gate uses are
the same number, and it is the lower bound.

Why readiness has five states rather than a boolean
-----------------------------------------------------
Because "ready" and "not ready" cannot express the situation this product is
usually in: everything measured is passing, and not enough has been measured
to promise anything. That is READY FOR CONTROLLED DEMO — a real state with a
real meaning (a demo somebody is driving, on questions inside the tested
envelope), and it is the honest answer far more often than either extreme.

VERIFIED FOR CURRENT RELEASE is deliberately hard to reach. It requires an
approved release, live verification against it, no critical failures, and a
demonstrated precision claim. A product that reached its top readiness state
easily would have a top state that meant nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.validation import intervals as me

CAPABILITY_VERSION = "1.0.0"

# ---------------------------------------------------- §103's eighteen
INTENT = "intent"
SAME_TURN = "same_turn_coreference"
MULTI_TURN = "multi_turn_context"
OBJECTIVE_COVERAGE = "objective_coverage"
CONCEPTS = "concepts"
DATASETS = "datasets"
RELATIONSHIPS = "relationships"
PERIODS_GRAIN = "periods_and_grain"
PLAN = "plan"
QUERY = "query"
RESULT = "result"
INVARIANTS = "invariants"
GROUNDING = "grounding"
INTERPRETATION = "interpretation"
VISUALIZATION = "visualization"
TRACE = "trace"
ABSTENTION = "abstention"
AGENT_SELECTION = "agent_selection"

CAPABILITIES: tuple[str, ...] = (
    INTENT, SAME_TURN, MULTI_TURN, OBJECTIVE_COVERAGE, CONCEPTS, DATASETS,
    RELATIONSHIPS, PERIODS_GRAIN, PLAN, QUERY, RESULT, INVARIANTS, GROUNDING,
    INTERPRETATION, VISUALIZATION, TRACE, ABSTENTION, AGENT_SELECTION,
)

#: What each capability IS, in a sentence a credit person can read. The Studio
#: is for Model Risk and Data Stewards as much as for engineers, and
#: "objective_coverage: 0.94" tells neither of them anything.
MEANS: dict[str, str] = {
    INTENT: "Reading what kind of thing the question is asking for.",
    SAME_TURN: "Resolving 'it' and 'those' to something named earlier in the "
               "same sentence.",
    MULTI_TURN: "Carrying the population and period from the previous turn "
                "into this one.",
    OBJECTIVE_COVERAGE: "Answering every clause of a question that asked for "
                        "three things.",
    CONCEPTS: "Mapping the words used to the governed credit-risk concepts "
              "they mean.",
    DATASETS: "Choosing the published, authoritative dataset rather than the "
              "nearest one.",
    RELATIONSHIPS: "Joining two sources along a governed path at the right "
                   "grain.",
    PERIODS_GRAIN: "Getting the window and the level of detail right.",
    PLAN: "Producing an analysis plan that satisfies the contract.",
    QUERY: "Compiling the plan to SQL that computes what the plan says.",
    RESULT: "Returning the right shape, columns and order.",
    INVARIANTS: "Checking the arithmetic the answer has to satisfy before "
                "showing it.",
    GROUNDING: "Every figure in the prose tracing to something computed.",
    INTERPRETATION: "Saying what the numbers mean without saying more than "
                    "they support.",
    VISUALIZATION: "Choosing a chart the data's shape supports, or a table.",
    TRACE: "The Trace matching what actually ran.",
    ABSTENTION: "Declining rather than guessing when the data is not held.",
    AGENT_SELECTION: "Sending the work to the right specialist.",
}

#: Capabilities where a failure means the answer asserts something untrue.
#: A critical failure in one of these blocks a demo whatever the average says.
CRITICAL: frozenset[str] = frozenset({
    GROUNDING, INVARIANTS, RELATIONSHIPS, PERIODS_GRAIN, TRACE, RESULT})

# ---------------------------------------------------------- trend
IMPROVING = "IMPROVING"
STEADY = "STEADY"
DEGRADING = "DEGRADING"
#: Fewer than two evaluations. A trend from one point is a line through one
#: point, and drawing it is the most common way a dashboard lies.
NO_TREND = "NOT_ENOUGH_HISTORY"

TRENDS: tuple[str, ...] = (IMPROVING, STEADY, DEGRADING, NO_TREND)

#: How much a rate must move between evaluations before it is a trend rather
#: than noise.
TREND_AT = 2.0

# ---------------------------------------------------------- status
HEALTHY = "HEALTHY"
WATCH = "WATCH"
FAILING = "FAILING"
#: Nothing has evaluated it. Never HEALTHY: the whole product runs on the rule
#: that an unmeasured thing is unknown rather than good.
UNMEASURED = "NOT_EVALUATED"

STATUSES: tuple[str, ...] = (HEALTHY, WATCH, FAILING, UNMEASURED)

#: Lower bound, not point estimate, in both cases.
HEALTHY_AT = 90.0
WATCH_AT = 75.0


@dataclass
class Capability:
    """One of §103's eighteen rows."""

    capability: str
    passed: int = 0
    total: int = 0
    critical_failures: list[str] = field(default_factory=list)
    last_evaluated: str = ""
    #: The previous evaluation's lower bound, for the trend.
    previous_lower: float | None = None

    @property
    def rate(self) -> me.Rate:
        return me.rate(self.capability, self.passed, self.total)

    @property
    def critical(self) -> bool:
        return self.capability in CRITICAL

    @property
    def trend(self) -> str:
        if self.previous_lower is None or not self.total:
            return NO_TREND
        moved = self.rate.lower - self.previous_lower
        if moved > TREND_AT:
            return IMPROVING
        if moved < -TREND_AT:
            return DEGRADING
        return STEADY

    @property
    def status(self) -> str:
        """The row's colour, from the LOWER bound and the critical failures.

        A critical failure is FAILING whatever the rate. The alternative is a
        green row over a grounding defect, which is the exact shape of a
        dashboard nobody should trust.
        """
        if self.critical_failures:
            return FAILING
        if not self.rate.reportable:
            return UNMEASURED
        if self.rate.lower >= HEALTHY_AT:
            return HEALTHY
        if self.rate.lower >= WATCH_AT:
            return WATCH
        return FAILING

    def sentence(self) -> str:
        """What the row says out loud.

        Never a bare percentage. §103's instruction is that the display must
        not imply certainty the sample does not support, and a number with no
        interval beside it implies exactly that.
        """
        if not self.total:
            return (f"{MEANS.get(self.capability, self.capability)} Nothing "
                    "has evaluated this.")
        if self.critical_failures:
            return (f"{self.passed} of {self.total} passed, and "
                    f"{len(self.critical_failures)} critical failure(s): "
                    + "; ".join(self.critical_failures[:2]) + ".")
        return self.rate.sentence()

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "means": MEANS.get(self.capability, ""),
            "score": self.rate.to_dict(),
            "case_count": self.total,
            "trend": self.trend,
            "critical": self.critical,
            "critical_failures": list(self.critical_failures),
            "last_evaluated": self.last_evaluated or "never",
            "status": self.status,
            "sentence": self.sentence(),
        }


def health(rows: list[Capability]) -> dict[str, Any]:
    """§103's capability health block.

    Every one of the eighteen appears, including the ones nobody measured —
    listed as NOT_EVALUATED rather than omitted, because a capability missing
    from a health table reads as one that does not exist.
    """
    seen = {row.capability: row for row in rows}
    complete = [seen.get(name, Capability(capability=name))
                for name in CAPABILITIES]
    critical = [row.capability for row in complete if row.critical_failures]
    return {
        "version": CAPABILITY_VERSION,
        "capabilities": [row.to_dict() for row in complete],
        "critical_failures": critical,
        "unmeasured": [row.capability for row in complete
                       if row.status == UNMEASURED],
        "failing": [row.capability for row in complete
                    if row.status == FAILING],
        # There is no aggregate capability score, on purpose. Averaging
        # eighteen dimensions of which one is a grounding defect produces a
        # comfortable number and hides the only row that matters.
        "no_aggregate_score": True,
    }


# ---------------------------------------------------------------------------
# §104 — client-demo readiness
# ---------------------------------------------------------------------------

NOT_READY = "NOT_READY"
LIMITED = "LIMITED"
CONTROLLED_DEMO = "READY_FOR_CONTROLLED_DEMO"
VERIFIED = "VERIFIED_FOR_CURRENT_RELEASE"
READINESS_STALE = "STALE"

READINESS: tuple[str, ...] = (NOT_READY, LIMITED, CONTROLLED_DEMO, VERIFIED,
                              READINESS_STALE)

READINESS_MEANS: dict[str, str] = {
    NOT_READY: "Something is failing that would be visible to a client. Do "
               "not demonstrate.",
    LIMITED: "It works, and enough is failing or unmeasured that a "
             "demonstration should stay on prepared ground.",
    CONTROLLED_DEMO: "Everything measured is passing, and not enough has been "
                     "measured to promise more. Safe for a demonstration "
                     "somebody is driving.",
    VERIFIED: "An approved release, verified live against it, with a "
              "precision claim the evidence supports.",
    READINESS_STALE: "The verification describes a version of CreditProbe "
                     "that has since changed.",
}


@dataclass
class Signals:
    """§104's inputs. Every one is a fact somebody else established."""

    release_state: str = ""
    provider_state: str = ""
    critical_suite_failures: list[str] = field(default_factory=list)
    accepted_precision: me.Rate | None = None
    numerical_failures: list[str] = field(default_factory=list)
    grounding_failures: list[str] = field(default_factory=list)
    objective_coverage_failures: list[str] = field(default_factory=list)
    trace_failures: list[str] = field(default_factory=list)
    unavailable_roles: list[str] = field(default_factory=list)
    stale_axes: list[str] = field(default_factory=list)
    live_verified_at: str = ""
    unmeasured_capabilities: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[str]:
        """What would be visible to a client. Any one of these is NOT_READY."""
        reasons: list[str] = []
        for label, items in (
                ("critical evaluation suites failing", self.critical_suite_failures),
                ("numerical correctness failures", self.numerical_failures),
                ("grounding failures", self.grounding_failures),
                ("objective coverage failures", self.objective_coverage_failures),
                ("Trace inconsistencies", self.trace_failures)):
            if items:
                reasons.append(f"{len(items)} {label}: "
                               + ", ".join(items[:3]))
        if self.unavailable_roles:
            reasons.append("model roles unavailable: "
                           + ", ".join(self.unavailable_roles))
        return reasons


#: The claim VERIFIED requires the evidence to support. Deliberately not
#: 99.99%: §104 says do not display a figure that is not demonstrated, and
#: 99.99% would need about thirty thousand consecutive clean cases.
VERIFIED_PRECISION_PCT = 90.0


@dataclass
class Readiness:
    """§104's honest status, and why."""

    state: str = NOT_READY
    reasons: list[str] = field(default_factory=list)
    #: What would move it up a state. A status with no route out of it is a
    #: verdict rather than a tool.
    to_improve: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": CAPABILITY_VERSION, "state": self.state,
                "means": READINESS_MEANS.get(self.state, ""),
                "reasons": list(self.reasons),
                "to_improve": list(self.to_improve),
                "states": list(READINESS),
                "sentence": self.sentence()}

    def sentence(self) -> str:
        head = READINESS_MEANS.get(self.state, self.state)
        if not self.reasons:
            return head
        return head + " " + "; ".join(self.reasons) + "."


def readiness(signals: Signals) -> Readiness:
    """§104, decided in order of severity.

    Stale is checked before anything else, because a stale verification is
    not a lower grade of verification — it is a statement about a product
    that no longer exists, and reading it as "mostly ready" is how a demo goes
    wrong in a way nobody predicted.
    """
    result = Readiness()

    if signals.stale_axes:
        result.state = READINESS_STALE
        result.reasons = ["these have changed since the last verification: "
                          + ", ".join(signals.stale_axes)]
        result.to_improve = ["re-run certification against the current "
                             "configuration"]
        return result

    blocking = signals.blocking
    if blocking:
        result.state = NOT_READY
        result.reasons = blocking
        result.to_improve = ["fix the failures above; none of them is a "
                             "presentation problem"]
        return result

    precision = signals.accepted_precision
    demonstrated = bool(precision
                        and precision.supports(VERIFIED_PRECISION_PCT))

    if (signals.release_state == "APPROVED" and signals.live_verified_at
            and demonstrated and not signals.unmeasured_capabilities):
        result.state = VERIFIED
        result.reasons = [
            f"approved release, verified live on {signals.live_verified_at}",
            precision.sentence()]
        return result

    if signals.provider_state in ("OFFLINE", "DEGRADED", ""):
        result.state = LIMITED
        result.reasons = [
            f"the AI provider reports {signals.provider_state or 'no state'}, "
            "so the live path cannot be shown"]
        result.to_improve = ["restore the provider and re-run the live check"]
        return result

    if signals.unmeasured_capabilities:
        result.state = CONTROLLED_DEMO
        result.reasons = [
            "everything measured is passing",
            f"{len(signals.unmeasured_capabilities)} capabilities have not "
            "been evaluated: "
            + ", ".join(signals.unmeasured_capabilities[:4])]
        result.to_improve = [
            "evaluate the unmeasured capabilities",
            "run a certification against an approved release"]
        return result

    if not demonstrated:
        result.state = CONTROLLED_DEMO
        result.reasons = [
            "everything measured is passing",
            precision.sentence() if precision else
            "accepted-answer precision has not been measured"]
        result.to_improve = [
            f"a claim of {VERIFIED_PRECISION_PCT}% needs a lower bound above "
            "it, which needs more clean cases"]
        return result

    result.state = CONTROLLED_DEMO
    result.reasons = ["everything measured is passing",
                      "no approved release is in force"]
    result.to_improve = ["cut and approve an Intelligence Release",
                         "run a live verification against it"]
    return result


__all__ = ["ABSTENTION", "AGENT_SELECTION", "CAPABILITIES",
           "CAPABILITY_VERSION", "CONCEPTS", "CONTROLLED_DEMO", "CRITICAL",
           "Capability", "DATASETS", "DEGRADING", "FAILING", "GROUNDING",
           "HEALTHY", "HEALTHY_AT", "IMPROVING", "INTENT", "INTERPRETATION",
           "INVARIANTS", "LIMITED", "MEANS", "MULTI_TURN", "NOT_READY",
           "NO_TREND", "OBJECTIVE_COVERAGE", "PERIODS_GRAIN", "PLAN", "QUERY",
           "READINESS", "READINESS_MEANS", "READINESS_STALE",
           "RELATIONSHIPS", "RESULT", "Readiness", "SAME_TURN", "STATUSES",
           "STEADY", "Signals", "TRACE", "TRENDS", "TREND_AT", "UNMEASURED",
           "VERIFIED", "VERIFIED_PRECISION_PCT", "VISUALIZATION", "WATCH",
           "WATCH_AT", "health", "readiness"]
