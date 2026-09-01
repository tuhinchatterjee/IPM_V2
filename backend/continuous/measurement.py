"""What the improvement actually was. §61-§63, §66-§68, §76-§78.

Five things this module refuses to do, and they are the point.

**It will not call more capture improvement.** §63: do not claim CreditProbe
learned 15% more merely because more cases were added. `quality_verdict()`
reports quantity and quality as two blocks and, where quantity rose with no
measured lift, says so in §63's own words.

**It will not report a development improvement as an improvement.**
`overfitting()` compares the two partitions and names the gap. Development
+8 pp with validation +0.5 pp is §76's worked example, and it is POSSIBLE
OVERFITTING rather than a win.

**It will not attribute what it cannot isolate.** §78's waterfall shows an
UNATTRIBUTED / INTERACTION bar rather than forcing the components to sum. A
waterfall that always balances is a waterfall somebody made balance.

**It will not report a percentage without its sample.** §77: do not claim
"improved 12%" without showing sample context. Every figure here travels
with a case count and an evidence level.

**It will not let a critical validation regression pass.** §76's closing
line, enforced in `may_activate()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

MEASUREMENT_VERSION = "1.0.0"

# ---------------------------------------------------------- §62's labels

IMPROVED = "IMPROVED"
UNCHANGED = "UNCHANGED"
MIXED = "MIXED"
REGRESSED = "REGRESSED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT EVIDENCE"
STALE = "STALE"

LABELS: tuple[str, ...] = (IMPROVED, UNCHANGED, MIXED, REGRESSED,
                           INSUFFICIENT_EVIDENCE, STALE)

# ---------------------------------------------------------- §77's evidence

HIGH_EVIDENCE = "HIGH EVIDENCE"
MODERATE_EVIDENCE = "MODERATE EVIDENCE"
LOW_EVIDENCE = "LOW EVIDENCE"
NO_EVIDENCE = "INSUFFICIENT EVIDENCE"

EVIDENCE_LEVELS: tuple[str, ...] = (HIGH_EVIDENCE, MODERATE_EVIDENCE,
                                    LOW_EVIDENCE, NO_EVIDENCE)

#: Below this a difference is not distinguishable from noise. The same
#: number the Lift Lab uses, deliberately: two thresholds for "enough cases"
#: would be two answers to the same question.
MINIMUM_CASES = 30
#: Below this, reporting a percentage at all is misleading.
TRIVIAL_CASES = 12
#: Percentage points below which a change is not material.
MATERIAL_POINTS = 1.0
#: A run older than this is measuring a system that no longer exists.
STALE_DAYS = 30


class MeasurementError(Exception):
    """A measurement that may not be reported, and why."""


# ------------------------------------------------------------- §61


@dataclass
class Change:
    """One score before and after, in §61's three forms.

    §61's worked example is 82.0% → 88.5%, which is +6.5 percentage points,
    +7.93% relative, and 36.11% of the error removed. All three are true and
    they say different things: the first is what a reader should quote, the
    second is what a vendor quotes, and the third is what an engineer cares
    about. Reporting only the second is how a 2 pp move on a small base
    becomes "a 40% improvement".
    """

    label: str
    before: float
    after: float
    cases: int = 0
    critical_fixed: int = 0
    critical_introduced: int = 0
    coverage: float = 0.0
    partition: str = ""

    @property
    def points(self) -> float:
        """Percentage-POINT change. What §61 leads with, and what to quote."""
        return round((self.after - self.before) * 100, 2)

    @property
    def relative(self) -> float:
        """Relative change. Flattering on a small base, and says so."""
        if self.before == 0:
            return 0.0
        return round((self.after - self.before) / self.before * 100, 2)

    @property
    def error_reduction(self) -> float:
        """How much of the remaining error was removed."""
        error = 1.0 - self.before
        if error <= 0:
            return 0.0
        return round((self.after - self.before) / error * 100, 2)

    @property
    def evidence(self) -> str:
        if self.cases < TRIVIAL_CASES:
            return NO_EVIDENCE
        if self.cases < MINIMUM_CASES:
            return LOW_EVIDENCE
        if self.cases < MINIMUM_CASES * 4:
            return MODERATE_EVIDENCE
        return HIGH_EVIDENCE

    @property
    def verdict(self) -> str:
        if self.cases < MINIMUM_CASES:
            return INSUFFICIENT_EVIDENCE
        if self.critical_introduced:
            return REGRESSED
        if abs(self.points) < MATERIAL_POINTS:
            return UNCHANGED
        return IMPROVED if self.points > 0 else REGRESSED

    def sentence(self) -> str:
        """§61's plain reading, with the sample §77 requires beside it."""
        if self.cases < TRIVIAL_CASES:
            return (f"{self.label}: {self.cases} case(s). Too few to report "
                    "a percentage — that is a result, not a small "
                    "improvement.")
        direction = "up" if self.points > 0 else (
            "down" if self.points < 0 else "unchanged at")
        moved = (f"{self.before * 100:.1f}% → {self.after * 100:.1f}%"
                 if self.points else f"{self.after * 100:.1f}%")
        return (f"{self.label}: {moved} — {direction} "
                f"{abs(self.points):.1f} percentage points "
                f"({self.relative:+.2f}% relative, "
                f"{self.error_reduction:.2f}% of the remaining error), "
                f"over {self.cases} case(s). {self.evidence}.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "partition": self.partition,
            "before": round(self.before, 4),
            "after": round(self.after, 4),
            "points": self.points,
            "relative_pct": self.relative,
            "error_reduction_pct": self.error_reduction,
            "cases": self.cases,
            "critical_fixed": self.critical_fixed,
            "critical_introduced": self.critical_introduced,
            "coverage": round(self.coverage, 4),
            "evidence": self.evidence,
            "verdict": self.verdict,
            "reads_as": self.sentence(),
        }


# ------------------------------------------------------------- §62


@dataclass
class DimensionResult:
    """§62. One dimension, on both partitions, with what caused it."""

    dimension: str
    development: Change
    validation: Change
    learning_items: tuple[str, ...] = ()
    releases: tuple[str, ...] = ()
    days_since_run: int = 0

    @property
    def verdict(self) -> str:
        """The honest label, weighing validation over development.

        Development is the set that was tuned against, so a development
        improvement that validation does not confirm is MIXED at best. A
        screen that took the development verdict would report every round of
        tuning as a win.
        """
        if self.days_since_run > STALE_DAYS:
            return STALE
        if self.validation.critical_introduced:
            return REGRESSED
        if self.validation.verdict == INSUFFICIENT_EVIDENCE:
            return (INSUFFICIENT_EVIDENCE
                    if self.development.verdict == INSUFFICIENT_EVIDENCE
                    else MIXED)
        if self.development.verdict == self.validation.verdict:
            return self.development.verdict
        if REGRESSED in (self.development.verdict, self.validation.verdict):
            return MIXED
        return MIXED

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "development": self.development.to_dict(),
            "validation": self.validation.to_dict(),
            "verdict": self.verdict,
            "learning_items_responsible": list(self.learning_items),
            "releases_responsible": list(self.releases),
            "days_since_run": self.days_since_run,
            "reads_as": self._sentence(),
        }

    def _sentence(self) -> str:
        if self.verdict == STALE:
            return (f"{self.dimension}: last measured {self.days_since_run} "
                    "days ago, against a system that has changed since.")
        if self.verdict == MIXED:
            return (f"{self.dimension}: development says "
                    f"{self.development.points:+.1f} pp and validation says "
                    f"{self.validation.points:+.1f} pp. Development is the "
                    "set that was tuned against, so the validation figure "
                    "is the one to believe.")
        return f"{self.dimension}: {self.validation.sentence()}"


# ------------------------------------------------------------- §63


def quality_verdict(*, quantity: dict[str, int],
                    dimensions: list[DimensionResult]) -> dict[str, Any]:
    """§63. Quantity and quality, reported apart.

    The sentence at the bottom is §63's, verbatim, for the case that
    actually happens: a quarter of diligent capture with nothing measurable
    to show for it yet. Saying so is not a failure report — most learning
    takes a release or two to land — but reporting it as improvement is.
    """
    captured = sum(v for k, v in quantity.items() if k.startswith("new_"))
    measured = [d for d in dimensions
                if d.validation.verdict != INSUFFICIENT_EVIDENCE]
    improved = [d for d in measured if d.verdict == IMPROVED]
    regressed = [d for d in measured if d.verdict == REGRESSED]

    if not measured:
        headline = ("MORE KNOWLEDGE CAPTURED — NO MEASURED PERFORMANCE "
                    "IMPROVEMENT YET"
                    if captured else
                    "NOTHING CAPTURED AND NOTHING MEASURED IN THIS WINDOW")
    elif regressed:
        headline = (f"{len(regressed)} dimension(s) regressed on validation. "
                    "That is the finding, whatever the others did.")
    elif improved:
        headline = (f"{len(improved)} of {len(measured)} measured "
                    "dimension(s) improved on validation.")
    else:
        headline = ("MORE KNOWLEDGE CAPTURED — NO MEASURED PERFORMANCE "
                    "IMPROVEMENT YET")

    return {
        "headline": headline,
        "learning_quantity": dict(quantity),
        "learning_quality": {
            "dimensions_measured": len(measured),
            "dimensions_improved": len(improved),
            "dimensions_regressed": len(regressed),
            "development_deltas": {d.dimension: d.development.points
                                   for d in dimensions},
            "validation_deltas": {d.dimension: d.validation.points
                                  for d in dimensions},
            "critical_failures_fixed": sum(d.validation.critical_fixed
                                           for d in dimensions),
            "critical_failures_introduced": sum(
                d.validation.critical_introduced for d in dimensions),
        },
        "why_they_are_separate": (
            "Adding cases is not improving. §63: do not claim CreditProbe "
            "learned 15% more merely because more cases were added — the "
            "count went up and nothing established that any answer got "
            "better."
        ),
    }


# ------------------------------------------------------------- §76


#: §76's worked example: development +8 pp against validation +0.5 pp. The
#: gap, not either number, is the signal.
OVERFITTING_GAP_POINTS = 4.0
#: Below this, a validation move is not a confirmation of anything.
CONFIRMING_POINTS = 1.0


@dataclass
class Overfitting:
    """§76. Development improving while validation does not."""

    development_points: float = 0.0
    validation_points: float = 0.0
    affected: tuple[str, ...] = ()
    recent_changes: tuple[str, ...] = ()
    critical_validation_regressions: tuple[str, ...] = ()

    @property
    def gap(self) -> float:
        return round(self.development_points - self.validation_points, 2)

    @property
    def suspected(self) -> bool:
        if self.validation_points < 0 and self.development_points > 0:
            return True
        return (self.gap >= OVERFITTING_GAP_POINTS
                and self.validation_points < CONFIRMING_POINTS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "possible_overfitting": self.suspected,
            "development_delta_points": self.development_points,
            "validation_delta_points": self.validation_points,
            "gap_points": self.gap,
            "affected_families": list(self.affected),
            "recent_changes": list(self.recent_changes),
            "critical_validation_regressions":
                list(self.critical_validation_regressions),
            "recommended_review": self._recommendation(),
        }

    def _recommendation(self) -> str:
        if self.critical_validation_regressions:
            return ("Do not activate. §76: a release with critical "
                    "validation regressions does not go live, and the "
                    "development improvement is not a counter-argument.")
        if not self.suspected:
            return ("Development and validation moved together. That is "
                    "what generalisation looks like.")
        if self.validation_points < 0:
            return ("Development improved and validation got worse. That is "
                    "the clearest form of this: the fixes are specific to "
                    "the cases they were written against. Look at what "
                    "changed, and at whether those cases are representative "
                    "of anything.")
        return (f"Development moved {self.development_points:+.1f} pp and "
                f"validation {self.validation_points:+.1f} pp — a "
                f"{self.gap:.1f} point gap. The improvement has not been "
                "shown to generalise. Review the recent changes against "
                "the affected families before treating this as a win.")


def overfitting(dimensions: list[DimensionResult], *,
                recent_changes: tuple[str, ...] = ()) -> Overfitting:
    """Average the two partitions and compare. §76."""
    if not dimensions:
        return Overfitting(recent_changes=recent_changes)
    dev = sum(d.development.points for d in dimensions) / len(dimensions)
    val = sum(d.validation.points for d in dimensions) / len(dimensions)
    affected = tuple(d.dimension for d in dimensions
                     if d.development.points - d.validation.points
                     >= OVERFITTING_GAP_POINTS)
    critical = tuple(d.dimension for d in dimensions
                     if d.validation.critical_introduced)
    return Overfitting(
        development_points=round(dev, 2), validation_points=round(val, 2),
        affected=affected, recent_changes=recent_changes,
        critical_validation_regressions=critical)


def may_activate(dimensions: list[DimensionResult]) -> tuple[bool, str]:
    """§76's closing line, enforced.

    "Do not activate a release if critical validation regressions exist."
    Not weighed against the improvements — a critical failure on the
    out-of-sample set is a wrong answer the bank would have shown a client,
    and an average does not make it not one.
    """
    regressions = [d.dimension for d in dimensions
                   if d.validation.critical_introduced]
    if regressions:
        return False, (
            f"critical validation regressions on: {', '.join(regressions)}. "
            "§76: do not activate. This is not weighed against the "
            "improvements — a critical failure on the out-of-sample set is "
            "a wrong answer the bank would have shown a client.")
    return True, ""


# ------------------------------------------------------------- §78


#: §78's attribution sources, in §78's order.
SOURCES: tuple[str, ...] = (
    "Teaching Cases", "Blueprint changes", "Routing/model changes",
    "Judgment changes", "Regulatory learning", "Feedback fixes",
    "Brain imports",
)


@dataclass
class Contribution:
    """One attributed movement, and whether it was actually isolated."""

    source: str
    points: float
    #: True only when a change-isolation experiment measured this source on
    #: its own. §78: only use additive attribution where isolated
    #: evaluations support it.
    isolated: bool = False
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "points": round(self.points, 2),
                "isolated": self.isolated, "evidence": self.evidence}


def waterfall(*, starting: float, ending: float,
              contributions: list[Contribution],
              regressions: list[Contribution] | None = None
              ) -> dict[str, Any]:
    """§78's improvement waterfall, with the residual named rather than hidden.

    Only isolated contributions are attributed. Everything else — including
    the part that simply does not add up — goes into UNATTRIBUTED /
    INTERACTION, which §78 asks for by name. A waterfall that always
    balances is a waterfall somebody made balance, and the made-up bar is
    always the one a reader trusts most because it makes the picture work.
    """
    total = round((ending - starting) * 100, 2)
    attributed = [c for c in contributions if c.isolated]
    unattributed_sources = [c for c in contributions if not c.isolated]
    losses = list(regressions or [])

    accounted = (sum(c.points for c in attributed)
                 - sum(abs(c.points) for c in losses))
    residual = round(total - accounted, 2)

    return {
        "starting_validation_score": round(starting, 4),
        "current_validation_score": round(ending, 4),
        "total_points": total,
        "bars": (
            [c.to_dict() for c in attributed]
            + [{**c.to_dict(), "points": -abs(round(c.points, 2))}
               for c in losses]
            + [{
                "source": "UNATTRIBUTED / INTERACTION",
                "points": residual,
                "isolated": False,
                "evidence": _residual_reason(unattributed_sources, residual),
            }]
        ),
        "sources_not_isolated": [c.source for c in unattributed_sources],
        "why_there_is_a_residual": (
            "§78: only use additive attribution where isolated evaluations "
            "support it. Where effects overlap the honest bar is "
            "UNATTRIBUTED / INTERACTION rather than forced additive maths — "
            "a waterfall that always balances is one somebody made balance."
        ),
    }


def _residual_reason(unattributed: list[Contribution],
                     residual: float) -> str:
    if unattributed:
        names = ", ".join(c.source for c in unattributed)
        return (f"{names} were not evaluated in isolation, so their effect "
                "cannot be separated from each other's or from the "
                "interaction between them.")
    if abs(residual) < 0.05:
        return "Everything measured is accounted for."
    return ("The isolated experiments do not fully account for the movement. "
            "Something changed that nobody attributed, and naming that is "
            "more useful than distributing it across the bars that exist.")


# ------------------------------------------------------------- §66, §67


def velocity(snapshots: list[Any], *, days: int = 30) -> dict[str, Any]:
    """§66. How fast learning is arriving, and how fast it is landing.

    Two rates, because they are the ones that diverge: an installation can
    capture forty observations a week and activate none, and the first
    number alone reads as a healthy learning system.
    """
    if not snapshots:
        return {"captured_per_day": 0.0, "activated_per_day": 0.0,
                "days": days,
                "note": "No snapshots in this window."}
    captured = sum(getattr(s, "new_learning_captured", 0) for s in snapshots)
    approved = sum(getattr(s, "new_learning_approved", 0) for s in snapshots)
    activated = sum(getattr(s, "new_learning_activated", 0)
                    for s in snapshots)
    span = max(days, 1)
    return {
        "days": days,
        "captured_per_day": round(captured / span, 2),
        "approved_per_day": round(approved / span, 2),
        "activated_per_day": round(activated / span, 2),
        "conversion": round(activated / captured, 4) if captured else 0.0,
        "note": (
            "Captured and activated are separate rates because they "
            "diverge. Forty observations a week with nothing activated is a "
            "backlog, and the capture rate alone reads as a healthy "
            "learning system."
        ),
    }


def attribution(dimension: DimensionResult) -> dict[str, Any]:
    """§67. What is believed to have caused one dimension's movement.

    Named as belief rather than as fact unless a change-isolation
    experiment established it. The list of learning items that landed in a
    window is a list of suspects, not a cause.
    """
    return {
        "dimension": dimension.dimension,
        "validation_points": dimension.validation.points,
        "learning_items": list(dimension.learning_items),
        "releases": list(dimension.releases),
        "established": False,
        "note": (
            "These are the changes that landed in the window, not the "
            "changes shown to have caused the movement. Establishing cause "
            "takes a change-isolation experiment; a list of what happened "
            "at the same time is a list of suspects."
        ),
    }
