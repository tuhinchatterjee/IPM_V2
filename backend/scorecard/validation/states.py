"""What a validation test result can be, and why nine states rather than three.

The temptation is PASS, FAIL and a null. It is the wrong shape, and the way
it is wrong is expensive: every reason a test did not produce a number
collapses into the same empty cell, and a validator reading that cell cannot
tell whether the model is fine, the data is missing, the cohort has not
matured, the sample is too small to say anything, the calculation broke, or
they are not allowed to see it. Those are six different conversations with
six different next actions, and one of them — "the outcome does not exist
yet" — is the single most common way a scorecard validation goes wrong in
practice, because a cohort with no realised defaults renders as 0.0% and
0.0% reads as excellent.

So the states are enumerated, and the enumeration is the contract:

  PASS                 measured, inside its limit
  WARNING              measured, inside its limit but close enough to matter
  FAIL                 measured, outside its limit
  UNAVAILABLE          the input does not exist in this deployment
  NOT_MATURED          the performance window has not closed, so no outcome
  INSUFFICIENT_SAMPLE  measured, but on too little to stand behind
  NOT_APPLICABLE       the test does not apply to this model
  CALCULATION_ERROR    it was attempted and it raised
  NOT_AUTHORISED       the caller may not see this

The first three carry a number. The rest carry a sentence and never a
number, because a state that means "no result" and a field that holds a
result are not allowed in the same object at the same time — `Result`
enforces that in `__post_init__` rather than trusting a caller.

On NOT_APPLICABLE versus UNAVAILABLE
--------------------------------------
Worth separating even though both mean "no number". NOT_APPLICABLE is a
statement about the model: a rank-order scorecard with no score-to-PD
mapping has no calibration to test, and never will, and a validation report
should say so and move on. UNAVAILABLE is a statement about this
deployment: the field exists in the design and is not populated here, which
is a finding about data rather than about the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STATES_VERSION = "1.0.0"

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"
NO_LIMIT = "NO_LIMIT"
UNAVAILABLE = "UNAVAILABLE"
NOT_MATURED = "NOT_MATURED"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
CALCULATION_ERROR = "CALCULATION_ERROR"
NOT_AUTHORISED = "NOT_AUTHORISED"

STATES: tuple[str, ...] = (
    PASS, WARNING, FAIL, NO_LIMIT, UNAVAILABLE, NOT_MATURED,
    INSUFFICIENT_SAMPLE, NOT_APPLICABLE, CALCULATION_ERROR, NOT_AUTHORISED,
)

#: The four that mean a number was produced. Three of them were also
#: compared against something; `NO_LIMIT` is the one that was not, and it
#: exists because the alternative is worse. A measured value with no
#: configured threshold has to be reported as *something*, and the obvious
#: choices are both false: PASS says it was checked and cleared, FAIL says
#: it was checked and breached. Neither happened. A count of monotonicity
#: breaks or wrong-signed coefficients reported as PASS because nobody set a
#: limit is exactly the kind of green tick this whole state model exists to
#: prevent.
MEASURED: frozenset[str] = frozenset({PASS, WARNING, FAIL, NO_LIMIT})

#: The six that mean there is no number. Never rendered as zero, never
#: aggregated into an average, never counted as a pass.
UNMEASURED: frozenset[str] = frozenset(STATES) - MEASURED

#: The two that a model owner has to act on. `NO_LIMIT` is deliberately not
#: among them: the number may be perfectly fine, and nobody knows, which is a
#: governance gap rather than a model finding.
ADVERSE: frozenset[str] = frozenset({FAIL, WARNING})

STATE_LABELS: dict[str, str] = {
    PASS: "Pass",
    WARNING: "Warning",
    FAIL: "Fail",
    NO_LIMIT: "No approved limit",
    UNAVAILABLE: "Not available",
    NOT_MATURED: "Not yet matured",
    INSUFFICIENT_SAMPLE: "Insufficient sample",
    NOT_APPLICABLE: "Not applicable",
    CALCULATION_ERROR: "Calculation failed",
    NOT_AUTHORISED: "Not authorised",
}

STATE_MEANING: dict[str, str] = {
    PASS: "Measured, and inside its configured limit.",
    WARNING: "Measured and inside its limit, but close enough to it that the "
             "next period is worth watching.",
    FAIL: "Measured, and outside its configured limit.",
    NO_LIMIT: "Measured, and compared against nothing, because no limit is "
              "configured for this test on this model. The number is real; "
              "whether it is acceptable is undecided.",
    UNAVAILABLE: "The input this test needs is not populated in this "
                 "deployment. A finding about data, not about the model.",
    NOT_MATURED: "The performance window for this cohort has not closed, so "
                 "no realised outcome exists. Not zero defaults — no outcome.",
    INSUFFICIENT_SAMPLE: "There were too few observations or too few events "
                         "to stand behind a number.",
    NOT_APPLICABLE: "This test does not apply to this model. A rank-order "
                    "scorecard with no score-to-PD mapping has no calibration "
                    "to test.",
    CALCULATION_ERROR: "The calculation was attempted and did not complete. "
                       "Reported rather than swallowed.",
    NOT_AUTHORISED: "You are not authorised to see this result.",
}

#: Severity, for ranking a list of results. Not a score — an ordering, so
#: that a screen showing thirty results puts the ones that need a person
#: first. `UNMEASURED` states sit below `WARNING` deliberately: "we could not
#: measure it" is a real problem, and it is a smaller problem than "we
#: measured it and it breached".
SEVERITY_ORDER: dict[str, int] = {
    FAIL: 0,
    WARNING: 1,
    NO_LIMIT: 2,
    CALCULATION_ERROR: 3,
    UNAVAILABLE: 4,
    INSUFFICIENT_SAMPLE: 5,
    NOT_MATURED: 6,
    NOT_AUTHORISED: 7,
    NOT_APPLICABLE: 8,
    PASS: 9,
}


class ResultError(ValueError):
    """A result was constructed in a shape that cannot be true."""


@dataclass(frozen=True)
class Result:
    """One validation test result.

    Frozen on purpose. A result is evidence: it is produced once, cited by a
    finding, quoted in a report and reproduced from its own metadata. A
    mutable result is one that can be edited after the finding that cites it
    was raised, and then the two disagree with no record of which changed.
    """

    test_id: str
    state: str
    #: The measured value, or None. Present only for a MEASURED state — see
    #: `__post_init__`, which refuses the combination rather than trusting a
    #: caller to remember.
    value: float | None = None
    #: What the value was compared against, and where that limit came from.
    #: A limit with no source becomes a regulatory requirement the third time
    #: somebody reads the table.
    limit: float | None = None
    limit_source: str = ""
    comparison_value: float | None = None
    #: Why, in one sentence a validator can put in a report unedited.
    detail: str = ""
    #: What to do about it, where the state implies something.
    remedy: str = ""

    # ---- what it was computed over ---------------------------------------
    model_id: str = ""
    model_version: str = ""
    dataset: str = ""
    period: str = ""
    reference_period: str = ""
    segment: str = ""
    observations: int = 0
    matured_observations: int = 0
    events: int = 0

    # ---- how it was computed ---------------------------------------------
    calculation_version: str = ""
    score_direction: str = ""
    method: str = ""
    limitations: tuple[str, ...] = ()
    chart: dict[str, Any] = field(default_factory=dict)
    table: list[dict[str, Any]] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ResultError(
                f"{self.state!r} is not a validation result state. It is one "
                f"of: {', '.join(STATES)}.")
        if self.state in MEASURED and self.value is None:
            raise ResultError(
                f"{self.test_id} is {self.state} with no value. A measured "
                "state that carries no number is how a result that was never "
                "computed comes to be reported as a pass.")
        if self.state in UNMEASURED and self.value is not None:
            raise ResultError(
                f"{self.test_id} is {self.state} and carries the value "
                f"{self.value!r}. A state that means 'there is no number' and "
                "a field holding one cannot both be true, and the field is "
                "what a chart will read.")
        if self.state in UNMEASURED and not self.detail:
            raise ResultError(
                f"{self.test_id} is {self.state} with no explanation. The "
                "explanation IS the result — a blank cell tells a validator "
                "nothing they can act on.")

    # ---- reading it ------------------------------------------------------

    @property
    def measured(self) -> bool:
        return self.state in MEASURED

    @property
    def adverse(self) -> bool:
        return self.state in ADVERSE

    @property
    def severity(self) -> int:
        return SEVERITY_ORDER[self.state]

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]

    def to_dict(self) -> dict[str, Any]:
        return {
            "states_version": STATES_VERSION,
            "test_id": self.test_id,
            "state": self.state,
            "state_label": self.label,
            "state_meaning": STATE_MEANING[self.state],
            "measured": self.measured,
            "value": self.value,
            "limit": self.limit,
            "limit_source": self.limit_source,
            "comparison_value": self.comparison_value,
            "detail": self.detail,
            "remedy": self.remedy,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dataset": self.dataset,
            "period": self.period,
            "reference_period": self.reference_period,
            "segment": self.segment,
            "observations": self.observations,
            "matured_observations": self.matured_observations,
            "events": self.events,
            "calculation_version": self.calculation_version,
            "score_direction": self.score_direction,
            "method": self.method,
            "limitations": list(self.limitations),
            "chart": dict(self.chart),
            "table": list(self.table),
            "lineage": dict(self.lineage),
            "severity": self.severity,
        }


# ------------------------------------------------------- constructing them


def measured(test_id: str, state: str, value: float, **kw: Any) -> Result:
    """A result that carries a number."""
    if state not in MEASURED:
        raise ResultError(f"{state} is not a measured state.")
    return Result(test_id=test_id, state=state, value=float(value), **kw)


def not_matured(test_id: str, *, period: str, closes: str, **kw: Any) -> Result:
    """No outcome yet, and when there will be one.

    The second half is what makes it useful. "Not available" without a date
    reads as broken; "the window closes in 2025-05" reads as governed.
    """
    return Result(
        test_id=test_id, state=NOT_MATURED,
        detail=(f"The performance window for {period} has not closed. No "
                f"realised outcome exists until {closes}, so this test has "
                "nothing to measure — which is not the same as no defaults."),
        remedy=f"Re-run once {period} has matured, from {closes}.",
        period=period, **kw)


def insufficient(test_id: str, *, observations: int, events: int,
                 minimum_observations: int, minimum_events: int,
                 **kw: Any) -> Result:
    """Measured on too little to stand behind.

    Says both numbers and both floors, because "insufficient" without them
    is an opinion and with them is a fact a reader can check.
    """
    return Result(
        test_id=test_id, state=INSUFFICIENT_SAMPLE,
        detail=(f"{observations:,} observations carrying {events:,} events. "
                f"This test needs at least {minimum_observations:,} "
                f"observations and {minimum_events:,} events before a result "
                "is worth reporting."),
        remedy="Widen the period, or the segment, or both.",
        observations=observations, events=events, **kw)


def unavailable(test_id: str, *, what: str, remedy: str = "",
                **kw: Any) -> Result:
    """The input is not there. A finding about the deployment, not the model.

    `remedy` is overridable because some absences have a specific answer —
    "stamp the version on every scored row" is more use than the general
    one — and a caller that has that answer should not have to restate the
    default alongside it.
    """
    return Result(
        test_id=test_id, state=UNAVAILABLE,
        detail=f"{what} is not populated in this deployment.",
        remedy=remedy or (
            "A data finding rather than a model finding: the field exists "
            "in the design and is not being supplied."),
        **kw)


def not_applicable(test_id: str, *, why: str, **kw: Any) -> Result:
    return Result(test_id=test_id, state=NOT_APPLICABLE, detail=why, **kw)


def failed(test_id: str, *, error: Exception | str, **kw: Any) -> Result:
    """It raised. Reported, never swallowed.

    A calculation that fails silently and leaves a gap is indistinguishable
    on screen from one that was never requested, and the difference decides
    whether anybody investigates.
    """
    said = (f"{type(error).__name__}: {error}" if isinstance(error, Exception)
            else str(error))
    return Result(
        test_id=test_id, state=CALCULATION_ERROR,
        detail=f"The calculation did not complete. {said}",
        remedy="Reported rather than swallowed. This is a defect to raise, "
               "not a model finding.",
        **kw)


def not_authorised(test_id: str, **kw: Any) -> Result:
    return Result(
        test_id=test_id, state=NOT_AUTHORISED,
        detail="You are not authorised to see this result.", **kw)


def rank(results: list[Result]) -> list[Result]:
    """Most in need of a person first, then by how far outside the limit."""
    def key(made: Result) -> tuple[int, float]:
        distance = 0.0
        if made.measured and made.limit is not None and made.value is not None:
            distance = -abs(made.value - made.limit)
        return (made.severity, distance)

    return sorted(results, key=key)


def tally(results: list[Result]) -> dict[str, int]:
    """How many of each state. Every state present, including the zeroes.

    Zeroes included deliberately: a summary that omits NOT_MATURED because
    there were none this time trains a reader to stop looking for it.
    """
    counts = dict.fromkeys(STATES, 0)
    for made in results:
        counts[made.state] += 1
    return counts


__all__ = [
    "ADVERSE", "CALCULATION_ERROR", "FAIL", "INSUFFICIENT_SAMPLE", "MEASURED",
    "NOT_APPLICABLE", "NOT_AUTHORISED", "NOT_MATURED", "NO_LIMIT", "PASS",
    "SEVERITY_ORDER", "STATES", "STATES_VERSION", "STATE_LABELS",
    "STATE_MEANING", "UNAVAILABLE", "UNMEASURED", "WARNING", "Result",
    "ResultError", "failed", "insufficient", "measured", "not_applicable",
    "not_authorised", "not_matured", "rank", "tally", "unavailable",
]
