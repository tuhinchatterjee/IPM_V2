"""
What an accuracy number is allowed to claim.

The problem
-----------
"99.99% precision" over a hundred cases is not a measurement. A hundred cases
with zero errors is consistent with a true error rate of 3% — you would see a
clean run about one time in twenty. Reporting 100% from it, and then a target
of 99.99%, is two claims neither of which the evidence supports.

So every rate reported by this factory carries a **confidence interval**, and
the release gate compares the *lower bound* against the threshold rather than
the point estimate. A product that says "99.99%" when it has seen a hundred
cases is making the same mistake as a product that says CONNECTED because a key
is present.

Wilson rather than the normal approximation
-------------------------------------------
The textbook interval — p ± 1.96·√(p(1−p)/n) — is degenerate exactly where this
is used: at p = 1 it gives a width of zero, which reads as certainty from a
sample that has none. Wilson's interval is well behaved at the boundaries, needs
no extra dependency, and is what any statistician reviewing a model-risk
document would expect to see.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: 95% two-sided, the convention for a model-risk document.
Z = 1.959963984540054

#: How many observations before a rate is reported as a rate at all. Below
#: this the interval is so wide that quoting a percentage misleads more than
#: the raw counts would.
MIN_OBSERVATIONS = 30


@dataclass(frozen=True)
class Rate:
    """One measured rate, and what the sample can actually support."""

    name: str
    successes: int
    total: int
    lower: float
    upper: float

    @property
    def point(self) -> float:
        return (self.successes / self.total * 100.0) if self.total else 0.0

    @property
    def reportable(self) -> bool:
        return self.total >= MIN_OBSERVATIONS

    def supports(self, target_pct: float) -> bool:
        """Whether the evidence supports a claim of at least `target_pct`.

        The LOWER bound is compared, not the point estimate. A point estimate
        of 100% from 100 cases does not support a claim of 99.99%; its lower
        bound is around 96%, and that is the number an honest claim uses.
        """
        return self.reportable and self.lower >= target_pct

    def sentence(self) -> str:
        if not self.total:
            return f"{self.name}: no observations."
        if not self.reportable:
            return (f"{self.name}: {self.successes} of {self.total} — too few "
                    "observations to report as a rate.")
        return (f"{self.name}: {self.point:.2f}% "
                f"({self.successes}/{self.total}, 95% CI "
                f"{self.lower:.2f}–{self.upper:.2f}%)")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "successes": self.successes,
                "total": self.total, "point_pct": round(self.point, 4),
                "lower_pct": round(self.lower, 4),
                "upper_pct": round(self.upper, 4),
                "reportable": self.reportable, "sentence": self.sentence()}


def wilson(successes: int, total: int, z: float = Z) -> tuple[float, float]:
    """The Wilson score interval, as percentages.

    Chosen over the normal approximation because this is used at p = 1 more
    often than anywhere else, and there the textbook interval has zero width —
    it reports certainty from a sample that has none.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
            / denominator)
    return (max(0.0, (centre - half) * 100.0),
            min(100.0, (centre + half) * 100.0))


def rate(name: str, successes: int, total: int) -> Rate:
    lower, upper = wilson(successes, total)
    return Rate(name=name, successes=successes, total=total,
                lower=lower, upper=upper)


def cases_needed(target_pct: float, confidence: float = 0.95) -> int:
    """How many consecutive clean cases a claim of `target_pct` would need.

    The rule of three, generalised: with zero failures in n trials the upper
    bound on the failure rate is about −ln(1−confidence)/n. Reported so that a
    claim of 99.99% can be shown to need roughly thirty thousand clean cases,
    rather than argued about.
    """
    failure = max(1e-9, (100.0 - target_pct) / 100.0)
    return int(math.ceil(-math.log(1.0 - confidence) / failure))


@dataclass
class Accuracy:
    """Every dimension the certification measures, with its evidence."""

    rates: dict[str, Rate] = field(default_factory=dict)
    #: Cases where CreditProbe answered, as opposed to clarifying or abstaining.
    accepted: int = 0
    abstained: int = 0
    #: Cases that must never fail. A single one blocks certification, whatever
    #: the aggregate says.
    critical_failures: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.accepted + self.abstained

    @property
    def coverage(self) -> Rate:
        """How often CreditProbe answered rather than asking."""
        return rate("coverage", self.accepted, self.total)

    def add(self, name: str, successes: int, total: int) -> Rate:
        measured = rate(name, successes, total)
        self.rates[name] = measured
        return measured

    def claim(self, target_pct: float) -> dict[str, Any]:
        """Whether the accepted-answer precision supports a target.

        This is the one number the product is tempted to quote, so it is the
        one with the most machinery around it: the lower bound, the sample
        size, and how many clean cases the claim would actually take.
        """
        precision = self.rates.get("accepted_precision")
        supported = bool(precision and precision.supports(target_pct))
        needed = cases_needed(target_pct)
        verdict = (
            "demonstrated" if supported else
            "not yet demonstrated" if precision and precision.reportable else
            "statistically unproven")
        return {
            "target_pct": target_pct,
            "verdict": verdict,
            "supported": supported,
            "observed": precision.to_dict() if precision else None,
            "cases_needed_for_target": needed,
            "sentence": _claim_sentence(precision, target_pct, needed, verdict),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "rates": {k: v.to_dict() for k, v in self.rates.items()},
            "accepted": self.accepted,
            "abstained": self.abstained,
            "coverage": self.coverage.to_dict(),
            "critical_failures": list(self.critical_failures),
        }


def _claim_sentence(precision: Rate | None, target: float, needed: int,
                    verdict: str) -> str:
    if precision is None or not precision.total:
        return (f"A claim of {target}% is {verdict}: nothing has been measured "
                "against it.")
    if verdict == "demonstrated":
        return (f"A claim of {target}% is supported: the 95% lower bound on "
                f"accepted-answer precision is {precision.lower:.2f}% over "
                f"{precision.total} cases.")
    return (
        f"A claim of {target}% is {verdict}. The observed precision is "
        f"{precision.point:.2f}% over {precision.total} accepted answers, and "
        f"the 95% lower bound is {precision.lower:.2f}% — a run of about "
        f"{needed:,} consecutive clean cases would be needed to support "
        f"{target}% at 95% confidence.")


__all__ = ["MIN_OBSERVATIONS", "Z", "Accuracy", "Rate", "cases_needed", "rate",
           "wilson"]
