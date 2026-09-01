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

from dataclasses import dataclass, field
from typing import Any

# The Wilson maths lives in the backend rather than here. It started in this
# module, which is where certification maths belongs — then the Studio needed
# it, and the Studio is backend code. The import-graph test caught that
# immediately: the backend importing the factory is exactly what the
# sealed-holdout isolation forbids. One import of a statistics helper is
# harmless, and a boundary with one exception in it acquires a second.
#
# So the maths moved to `backend.validation.intervals` and this imports it,
# which is the permitted direction. There is still one implementation.
from backend.validation.intervals import (  # noqa: F401
    MIN_OBSERVATIONS,
    Rate,
    Z,
    cases_needed,
    rate,
    wilson,
)


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
