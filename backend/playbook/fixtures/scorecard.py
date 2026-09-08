"""
Deterministic scorecard statistics for the demonstration. Playbook §14.

The specification is specific about this: AUC/Gini/KS, PSI and calibration
figures shown as computed must actually be computed from synthetic inputs, or
else be labelled as fixed illustrative assumptions. Numbers typed into a fixture
and then described as a model run are the thing it forbids.

So this module builds a small synthetic score distribution from a seeded
generator and computes the statistics from it, with the same estimators a
validation pack would use:

* **AUC** by the Mann–Whitney identity — the probability that a randomly chosen
  bad scores worse than a randomly chosen good — which avoids trapezoid
  bookkeeping and ties handling getting quietly wrong.
* **Gini** as 2·AUC − 1.
* **KS** as the largest gap between the two cumulative distributions.
* **PSI** between a development and a recent sample, over fixed score bands.

Everything is derived. Change the generator's seed and every figure moves
together, which is exactly what a fixture that claims to be computed should do.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

FIXTURE_VERSION = "1.0.0"

#: Fixed, so every run of the demonstration produces the same report.
SEED = 20260630

#: Population sizes. Small enough to compute instantly, large enough that the
#: statistics are stable to two decimal places.
GOODS = 9_000
BADS = 1_000

#: Score bands used for PSI and for the band table in the report.
BANDS: tuple[tuple[str, int, int], ...] = (
    ("300–499", 300, 500),
    ("500–579", 500, 580),
    ("580–639", 580, 640),
    ("640–699", 640, 700),
    ("700–759", 700, 760),
    ("760–850", 760, 851),
)


def _clamp(value: float, low: int = 300, high: int = 850) -> int:
    return int(max(low, min(high, round(value))))


@dataclass(frozen=True)
class Sample:
    """One synthetic scored population."""

    label: str
    goods: tuple[int, ...]
    bads: tuple[int, ...]

    @property
    def all_scores(self) -> tuple[int, ...]:
        return self.goods + self.bads

    @property
    def bad_rate(self) -> float:
        return len(self.bads) / max(1, len(self.goods) + len(self.bads))


def _sample(label: str, *, seed: int, good_mean: float, bad_mean: float,
            spread: float = 70.0, goods: int = GOODS,
            bads: int = BADS) -> Sample:
    rng = random.Random(seed)
    return Sample(
        label=label,
        goods=tuple(_clamp(rng.gauss(good_mean, spread)) for _ in range(goods)),
        bads=tuple(_clamp(rng.gauss(bad_mean, spread)) for _ in range(bads)),
    )


def development() -> Sample:
    """The sample the scorecard was built on."""
    return _sample("Development", seed=SEED, good_mean=690, bad_mean=580)


def recent() -> Sample:
    """A later sample, shifted slightly — enough to move PSI, not to break it."""
    return _sample("Q2 2026", seed=SEED + 1, good_mean=679, bad_mean=574)


def auc(sample: Sample) -> float:
    """Area under the ROC curve, by the Mann–Whitney identity.

    The probability that a randomly chosen good outscores a randomly chosen
    bad, with ties counting a half. Counted over the merged ranking rather than
    by integrating a curve, so the figure is exact rather than approximated —
    and `bisect` does the ranking, because a hand-rolled binary search is a
    place to be subtly wrong in a way every downstream number inherits.
    """
    goods = sorted(sample.goods)
    total = len(goods) * len(sample.bads)
    if not total:
        return 0.5
    concordant = 0.0
    for bad in sample.bads:
        # Low score means high risk, so a good scoring ABOVE a bad is
        # concordant. Ties are the band between the two insertion points.
        above = len(goods) - bisect_right(goods, bad)
        ties = bisect_right(goods, bad) - bisect_left(goods, bad)
        concordant += above + 0.5 * ties
    return concordant / total


def gini(sample: Sample) -> float:
    return 2 * auc(sample) - 1


def ks(sample: Sample) -> float:
    """The largest separation between the two cumulative distributions."""
    goods = sorted(sample.goods)
    bads = sorted(sample.bads)
    worst = 0.0
    for score in sorted(set(goods) | set(bads)):
        good_share = bisect_right(goods, score) / len(goods)
        bad_share = bisect_right(bads, score) / len(bads)
        worst = max(worst, abs(good_share - bad_share))
    return worst


def _band_shares(scores: tuple[int, ...]) -> list[float]:
    total = max(1, len(scores))
    shares = []
    for _, low, high in BANDS:
        count = sum(1 for s in scores if low <= s < high)
        shares.append(count / total)
    return shares


def psi(base: Sample, compare: Sample) -> float:
    """Population Stability Index over the fixed score bands.

    An empty band would send a logarithm to infinity, so a floor is applied and
    the fact that it was applied is what `psi_table` reports.
    """
    floor = 1e-6
    total = 0.0
    for expected, actual in zip(_band_shares(base.all_scores),
                                _band_shares(compare.all_scores), strict=True):
        e, a = max(expected, floor), max(actual, floor)
        total += (a - e) * math.log(a / e)
    return total


def psi_table(base: Sample, compare: Sample) -> list[list[str]]:
    """The band-by-band contribution, as a report table."""
    floor = 1e-6
    rows: list[list[str]] = []
    for (label, _, _), expected, actual in zip(
        BANDS, _band_shares(base.all_scores), _band_shares(compare.all_scores),
        strict=True,
    ):
        e, a = max(expected, floor), max(actual, floor)
        contribution = (a - e) * math.log(a / e)
        rows.append([label, f"{expected * 100:.2f}", f"{actual * 100:.2f}",
                     f"{contribution:.4f}"])
    return rows


def band_performance(sample: Sample) -> list[list[str]]:
    """Observed bad rate by score band — the calibration evidence."""
    rows: list[list[str]] = []
    for label, low, high in BANDS:
        goods = sum(1 for s in sample.goods if low <= s < high)
        bads = sum(1 for s in sample.bads if low <= s < high)
        total = goods + bads
        rate = (bads / total * 100) if total else 0.0
        rows.append([label, str(total), str(bads), f"{rate:.2f}"])
    return rows


def headline() -> dict[str, str]:
    """Every statistic the demonstration quotes, computed once.

    The report, the chat, the workbook and the deck all read this, so they
    cannot disagree with each other.
    """
    dev, now = development(), recent()
    return {
        "development_auc": f"{auc(dev):.4f}",
        "development_gini": f"{gini(dev):.4f}",
        "development_ks": f"{ks(dev):.4f}",
        "recent_auc": f"{auc(now):.4f}",
        "recent_gini": f"{gini(now):.4f}",
        "recent_ks": f"{ks(now):.4f}",
        "psi": f"{psi(dev, now):.4f}",
        # The fall in discrimination, computed here rather than in the prose
        # that quotes it, so there is one place this arithmetic happens.
        "gini_change": f"{gini(now) - gini(dev):.4f}",
        "development_bad_rate": f"{dev.bad_rate * 100:.2f}",
        "recent_bad_rate": f"{now.bad_rate * 100:.2f}",
    }
