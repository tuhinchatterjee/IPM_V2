"""
What a rate is allowed to claim. The Wilson score interval.

Why this lives in the backend rather than in the factory
---------------------------------------------------------
It started in `intelligence_factory/metrics.py`, which is where the
certification maths belongs. Then the Studio needed it, and the Studio is
backend code — and the import-graph test caught it immediately, because the
backend importing the factory is exactly what the sealed-holdout isolation
forbids. One import of a statistics helper is harmless; a boundary with one
exception in it is a boundary that acquires a second.

So the maths moved here and the factory imports it, which is the permitted
direction. There is still one implementation.

The problem it solves
---------------------
"99.99% precision" over a hundred cases is not a measurement. A hundred cases
with zero errors is consistent with a true error rate of 3% — you would see a
clean run about one time in twenty. Reporting 100% from it, and then a target
of 99.99%, is two claims neither of which the evidence supports.

So every rate carries a confidence interval, and every gate compares the LOWER
BOUND against its threshold rather than the point estimate.

Wilson rather than the normal approximation
-------------------------------------------
The textbook interval — p ± 1.96·√(p(1−p)/n) — is degenerate exactly where
this is used: at p = 1 it gives a width of zero, which reads as certainty from
a sample that has none. Wilson's interval is well behaved at the boundaries,
needs no extra dependency, and is what any statistician reviewing a model-risk
document would expect to see.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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


__all__ = ["MIN_OBSERVATIONS", "Rate", "Z", "cases_needed", "rate", "wilson"]
