"""
Persistence versus noise. §74.

    "State the required history. Do not call a two-point change persistent."

The second sentence is the module's reason for existing. Two points define a
line, and a line looks like a trend to everybody who sees one. A quarter-on-
quarter movement is a movement; calling it a trend requires history, and the
minimum is stated rather than assumed so a reader can disagree with it.

Five verdicts, and the two people forget
-----------------------------------------
PERSISTENT and SPIKE are the ones anybody asks for. VOLATILE and REVERSING are
the ones the data often shows, and they lead somewhere different: a volatile
series means the measure is not telling you what you think, and a reversing one
means the thing you were worried about last quarter has partly unwound.
INSUFFICIENT_HISTORY is the honest answer more often than any of them.

Why several statistics rather than a slope
--------------------------------------------
A slope alone calls a series that rose four points and fell three "rising". A
sign-consistency count alone calls a series that crept up by nothing four times
"persistent". Monotonicity misses a step change. So the verdict reads several,
compares the latest movement against the series' own historical variation, and
says which statistic decided.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

PERSISTENCE_VERSION = "1.0.0"

PERSISTENT = "PERSISTENT"
SPIKE = "ONE_PERIOD_SPIKE"
VOLATILE = "VOLATILE"
REVERSING = "REVERSING"
INSUFFICIENT = "INSUFFICIENT_HISTORY"

VERDICTS: tuple[str, ...] = (PERSISTENT, SPIKE, VOLATILE, REVERSING,
                             INSUFFICIENT)

#: §74's floor, stated. Four observations give three movements, which is the
#: fewest that can distinguish a trend from a step followed by nothing.
MIN_PERIODS = 4

#: How many consecutive same-signed movements make a trend.
PERSISTENT_RUN = 3

#: A movement this many times the series' own historical standard deviation is
#: a spike rather than a continuation — the series has done something it does
#: not usually do.
SPIKE_SIGMA = 2.0

#: Above this ratio of standard deviation to mean absolute movement, the
#: series is too noisy for any verdict about direction to mean much.
VOLATILE_AT = 1.5

#: How much of the distance travelled ends up as net movement, below which
#: direction stops meaning anything. A series that swings +10, −15, +20, −22
#: travelled 67 to end 7 away from where it started, and no statement about
#: its direction is worth making. A magnitude test misses this entirely — its
#: standard deviation is perfectly ordinary relative to its typical movement —
#: which is why §74 lists sign consistency separately.
#:
#: Called efficiency because that is what it is: net drift over path length.
EFFICIENCY_AT = 0.3

#: A spike dominates: its movement is large against everything the series did
#: before it, not merely large. Without this a creeping series whose latest
#: step is slightly bigger than the last one reads as a spike.
SPIKE_DOMINANCE = 2.0


@dataclass
class Verdict:
    """Whether a movement is a trend, and what said so."""

    verdict: str = INSUFFICIENT
    periods: int = 0
    required_periods: int = MIN_PERIODS
    measures: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def determined(self) -> bool:
        return self.verdict != INSUFFICIENT

    def sentence(self) -> str:
        if self.verdict == INSUFFICIENT:
            return (f"There are {self.periods} periods of history; at least "
                    f"{self.required_periods} are needed to say whether this "
                    "persists.")
        return {
            PERSISTENT: f"The movement has continued in the same direction "
                        f"for {self.measures.get('run', 0)} consecutive "
                        "periods.",
            SPIKE: "This is a single-period movement, well outside what the "
                   "series usually does.",
            VOLATILE: "The series moves too much period to period for a "
                      "direction to mean much.",
            REVERSING: "The latest movement reverses the preceding trend.",
        }[self.verdict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PERSISTENCE_VERSION,
            "verdict": self.verdict,
            "sentence": self.sentence(),
            "periods": self.periods,
            "required_periods": self.required_periods,
            "measures": dict(self.measures),
            "reasons": list(self.reasons),
        }


def _slope(values: list[float]) -> float:
    """Ordinary least squares slope over evenly spaced periods."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    numerator = sum((i - mean_x) * (v - mean_y)
                    for i, v in enumerate(values))
    denominator = sum((i - mean_x) ** 2 for i in range(n))
    return numerator / denominator if denominator else 0.0


def _run(movements: list[float]) -> int:
    """Consecutive same-signed movements ending at the latest one."""
    if not movements:
        return 0
    sign = 1 if movements[-1] > 0 else (-1 if movements[-1] < 0 else 0)
    if not sign:
        return 0
    count = 0
    for value in reversed(movements):
        if (value > 0 and sign > 0) or (value < 0 and sign < 0):
            count += 1
        else:
            break
    return count


def assess(series: list[float], *,
           required_periods: int = MIN_PERIODS) -> Verdict:
    """§74's decision over an ordered series, oldest first.

    Order matters and is the caller's responsibility. A series handed over
    newest-first produces a confident answer about the wrong direction, which
    is why `sentence` names the run length rather than the direction: a reader
    seeing "four consecutive periods" against a chart that shows two will
    catch it.
    """
    values = [float(v) for v in series if v is not None]
    verdict = Verdict(periods=len(values), required_periods=required_periods)

    if len(values) < max(2, required_periods):
        verdict.verdict = INSUFFICIENT
        verdict.reasons.append(
            f"{len(values)} observations; {required_periods} required. Two "
            "points define a line, and a line looks like a trend.")
        return verdict

    movements = [b - a for a, b in zip(values, values[1:], strict=False)]
    latest = movements[-1]
    earlier = movements[:-1]
    spread = statistics.pstdev(earlier) if len(earlier) >= 2 else 0.0
    typical = (sum(abs(m) for m in earlier) / len(earlier)) if earlier else 0.0
    run = _run(movements)

    flips = sum(1 for a, b in zip(movements, movements[1:], strict=False)
                if a and b and (a > 0) != (b > 0))
    flip_rate = flips / (len(movements) - 1) if len(movements) > 1 else 0.0

    measures: dict[str, Any] = {
        "run": run,
        "sign_flips": flips,
        "flip_rate": flip_rate,
        "slope": _slope(values),
        "latest_movement": latest,
        "historical_sigma": spread,
        "typical_movement": typical,
        "monotonic": all(m >= 0 for m in movements)
        or all(m <= 0 for m in movements),
        "sign_consistency": (sum(1 for m in movements
                                 if (m > 0) == (latest > 0)) / len(movements)
                             if movements and latest else 0.0),
        "noise_ratio": (spread / typical) if typical else 0.0,
    }
    verdict.measures = measures

    # ---- the ladder, in the order the answers exclude one another --------
    #
    # A spike first, because a dominant single movement makes every other
    # statistic about the series a statistic about that movement.
    path = sum(abs(m) for m in movements)
    drift = abs(values[-1] - values[0])
    efficiency = (drift / path) if path else 0.0
    measures["path"] = path
    measures["drift"] = drift
    measures["efficiency"] = efficiency

    dominant = abs(latest) >= SPIKE_DOMINANCE * sum(abs(m) for m in earlier)
    # No run guard here on purpose. Dominance already says the earlier
    # movements were negligible, and a +0.2 followed by a +7.9 is not "two
    # consecutive movements in the same direction" in any sense a reader
    # would accept — the sign agreement is a coincidence, not a continuation.
    if dominant and (spread <= 0 or abs(latest) >= SPIKE_SIGMA * spread):
        verdict.verdict = SPIKE
        verdict.reasons.append(
            f"the latest movement ({latest:+.4g}) is larger than everything "
            f"the series did before it combined ({sum(abs(m) for m in earlier):.4g})")
        return verdict

    if run >= PERSISTENT_RUN:
        verdict.verdict = PERSISTENT
        verdict.reasons.append(
            f"{run} consecutive movements in the same direction")
        if measures["monotonic"]:
            verdict.reasons.append("the series is monotonic over the window")
        return verdict

    if earlier and latest and (latest > 0) != (earlier[-1] > 0) and \
            _run(earlier) >= 2:
        verdict.verdict = REVERSING
        verdict.reasons.append(
            f"the latest movement reverses a run of {_run(earlier)}")
        return verdict

    if len(movements) >= 3 and efficiency < EFFICIENCY_AT:
        verdict.verdict = VOLATILE
        verdict.reasons.append(
            f"the series travelled {path:.4g} to end {drift:.4g} from where "
            "it started; direction is not a property this series has")
        return verdict

    verdict.verdict = SPIKE
    verdict.reasons.append(
        "a single movement with no run behind it; a quarter-on-quarter change "
        "is a movement, not a trend")
    return verdict


__all__ = ["EFFICIENCY_AT", "INSUFFICIENT", "MIN_PERIODS", "PERSISTENCE_VERSION", "PERSISTENT",
           "PERSISTENT_RUN", "REVERSING", "SPIKE", "SPIKE_SIGMA",
           "SPIKE_DOMINANCE", "VERDICTS", "VOLATILE", "VOLATILE_AT",
           "Verdict", "assess"]
