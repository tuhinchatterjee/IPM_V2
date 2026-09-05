"""A second opinion on every validation statistic, computed from scratch.

This module exists to answer one question a validation product cannot answer
about itself: **are the numbers right?**

Nothing here imports `backend.scorecard.metrics`, `backend.scorecard.validation
.runner` or any other production kernel. It reads the parquet partitions
directly with pandas and recomputes each statistic from its textbook
definition, using a DIFFERENT ALGORITHM from the one in production wherever a
different one exists. That distinction is the whole value: a reimplementation
that shares the production algorithm reproduces the production bug, agrees
with it to fifteen decimal places, and proves nothing.

Where the algorithms differ
----------------------------
=========================  ==============================  ===================
Statistic                  Production                      Here
=========================  ==============================  ===================
AUC                        Mann-Whitney U on midranks,     Trapezoidal
                           over a compressed count table   integration of the
                                                           empirical ROC, plus
                                                           an exhaustive
                                                           pairwise count on a
                                                           subsample
KS                         From the same count table       Two sorted empirical
                                                           CDFs differenced
                                                           point by point
IV / WOE                   Binned through the registry's   Counted directly
                           binning spec                    from the raw column
                                                           against the same
                                                           declared edges
PSI                        Shared `_shift` helper over     Written out as the
                           reference and current           sum over bins of
                                                           (a-e)·ln(a/e)
Calibration                Score-band aggregation          Grouped means, and a
                                                           whole-portfolio
                                                           actual-versus-
                                                           predicted ratio
=========================  ==============================  ===================

The pairwise AUC is the strongest of these and the slowest: it counts every
(non-event, event) pair and scores concordance directly, which is the
definition rather than an identity derived from it. It runs on a bounded
subsample because the full cross-product is hundreds of millions of pairs; the
trapezoidal figure runs on everything.

Tolerances
-----------
Every comparison in `tests/reconciliation/test_numbers.py` states its own
tolerance and why. The default is 1e-9 — floating-point summation order, and
nothing else. Where a tolerance is looser than that, the reason is written
beside it and is about the ALGORITHM, never about making a test pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


#: The lake, found the same way the product finds it but read directly.
#: Deliberately not `runner._analytics_root`, which is private to the thing
#: under test.
def analytics_root() -> Path:
    from backend.config import settings

    return Path(settings.analytics_dir)


def read(dataset: str, periods: tuple[str, ...] = (),
         period_field: str = "") -> pd.DataFrame:
    """Every row of a dataset, or of the named partitions, straight off disk.

    No caching, no column pruning and no maturity filter. A reconciliation
    that inherited the production reader's filters would be reconciling
    against the same decisions it is supposed to be checking.
    """
    root = analytics_root() / dataset
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")

    frames: list[pd.DataFrame] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or "=" not in entry.name:
            continue
        key, value = entry.name.split("=", 1)
        if periods and value not in periods:
            continue
        for file in sorted(entry.glob("*.parquet")):
            part = pd.read_parquet(file)
            if (period_field or key) not in part.columns:
                part[period_field or key] = value
            frames.append(part)
    if not frames:
        raise FileNotFoundError(
            f"{dataset} has no partitions matching {periods or 'anything'}")
    return pd.concat(frames, ignore_index=True)


def partitions(dataset: str) -> tuple[str, ...]:
    root = analytics_root() / dataset
    if not root.exists():
        return ()
    found = [e.name.split("=", 1)[1] for e in root.iterdir()
             if e.is_dir() and "=" in e.name]

    def key(period: str) -> tuple[int, int]:
        bits = period.split("-")
        try:
            return (int(bits[0]), int(bits[1]) if len(bits) > 1 else 0)
        except (ValueError, IndexError):
            return (0, 0)

    return tuple(sorted(found, key=key))


# ------------------------------------------------------------- the cohort


@dataclass(frozen=True)
class Cohort:
    """Rows with a score and a realised outcome, and nothing else.

    `risk` is the score oriented so that HIGHER MEANS WORSE, whatever the
    model's own convention. Every statistic below is written for that
    orientation, so the direction is handled once, here, rather than by each
    formula remembering to.
    """

    risk: np.ndarray
    events: np.ndarray
    dropped: int

    @property
    def n(self) -> int:
        return int(self.events.size)

    @property
    def event_count(self) -> int:
        return int(self.events.sum())


def cohort(frame: pd.DataFrame, *, score: str, outcome: str,
           direction: str) -> Cohort:
    """Drop the rows that cannot carry a statistic, and say how many."""
    if score not in frame.columns:
        raise KeyError(f"{score} is not a column of this dataset")
    if outcome not in frame.columns:
        raise KeyError(f"{outcome} is not a column of this dataset")

    x = pd.to_numeric(frame[score], errors="coerce")
    y = pd.to_numeric(frame[outcome], errors="coerce")
    keep = x.notna() & y.notna()
    dropped = int((~keep).sum())

    values = x[keep].to_numpy(dtype=float)
    events = y[keep].to_numpy(dtype=float)
    events = (events > 0.5).astype(np.int8)

    if direction == "HIGHER_SCORE_IS_BETTER":
        risk = -values
    elif direction == "LOWER_SCORE_IS_BETTER":
        risk = values
    else:
        raise ValueError(
            f"{direction!r} is not a score direction. Without one there is no "
            "way to know which tail is the risky one, and an AUC computed "
            "without it is 1 minus the right answer half the time.")
    return Cohort(risk=risk, events=events, dropped=dropped)


# -------------------------------------------------------- discrimination


def auc_trapezoid(pool: Cohort) -> float:
    """AUC by integrating the empirical ROC curve.

    Sort descending by risk, walk the distinct thresholds, and accumulate the
    trapezoid between successive (FPR, TPR) points. Ties are handled by
    consuming a whole tied block at once, which is what makes the trapezoid —
    rather than a staircase — correct: a tied block moves right and up
    together, and the area under that diagonal is exactly the half-credit the
    rank-based definition gives a tie.
    """
    events = int(pool.events.sum())
    non = int(pool.n - events)
    if events == 0 or non == 0:
        raise ValueError(
            "one class is empty; AUC is undefined, not zero and not 0.5")

    order = np.argsort(-pool.risk, kind="mergesort")
    risk = pool.risk[order]
    hit = pool.events[order]

    area = 0.0
    tp = fp = 0
    last_tp = last_fp = 0
    i = 0
    while i < risk.size:
        j = i
        while j < risk.size and risk[j] == risk[i]:
            j += 1
        block = hit[i:j]
        tp += int(block.sum())
        fp += int(block.size - block.sum())
        # Trapezoid between the previous point and this one.
        area += (fp - last_fp) * (tp + last_tp) / 2.0
        last_tp, last_fp = tp, fp
        i = j
    return area / (events * non)


def auc_pairwise(pool: Cohort, *, cap: int = 4000, seed: int = 20260101
                 ) -> float:
    """AUC by counting concordant pairs. The definition, not an identity.

    Every (non-event, event) pair contributes 1 if the event carries the
    higher risk, 0.5 if they tie, 0 otherwise. That is what AUC *is*; the
    rank-sum formula is a shortcut for computing it. Bounded by `cap` per
    class because the full cross-product on the SME book is 1.4 x 10^8 pairs.

    Deterministic: the same rows are drawn every time, so a disagreement is a
    disagreement rather than a different sample.
    """
    events = pool.risk[pool.events == 1]
    non = pool.risk[pool.events == 0]
    if events.size == 0 or non.size == 0:
        raise ValueError("one class is empty; AUC is undefined")

    rng = np.random.default_rng(seed)
    if events.size > cap:
        events = events[rng.choice(events.size, cap, replace=False)]
    if non.size > cap:
        non = non[rng.choice(non.size, cap, replace=False)]

    greater = 0
    tied = 0
    for value in events:
        greater += int((non < value).sum())
        tied += int((non == value).sum())
    return (greater + 0.5 * tied) / (events.size * non.size)


def gini(auc: float) -> float:
    """Somers' D for a binary outcome. 2·AUC − 1, and nothing more."""
    return 2.0 * auc - 1.0


def ks(pool: Cohort) -> float:
    """The Kolmogorov-Smirnov separation, from two empirical CDFs.

    Built by sorting each class independently and stepping through the union
    of their values, rather than from the count table the production kernel
    shares with AUC. Two statistics computed off one intermediate agree with
    each other whether or not the intermediate is right.
    """
    events = np.sort(pool.risk[pool.events == 1])
    non = np.sort(pool.risk[pool.events == 0])
    if events.size == 0 or non.size == 0:
        raise ValueError("one class is empty; KS is undefined")

    thresholds = np.unique(np.concatenate([events, non]))
    # searchsorted with "right" counts values <= t, which is the empirical CDF.
    event_cdf = np.searchsorted(events, thresholds, side="right") / events.size
    non_cdf = np.searchsorted(non, thresholds, side="right") / non.size
    return float(np.max(np.abs(event_cdf - non_cdf)))


def rank_order(pool: Cohort, bands: int = 10) -> list[float]:
    """The event rate per risk band, riskiest band first.

    Bands are cut on quantiles of risk. A monotone decreasing sequence is what
    rank ordering means; this returns the sequence rather than a verdict, so
    the test can state its own reading of it.
    """
    order = np.argsort(-pool.risk, kind="mergesort")
    events = pool.events[order]
    edges = np.linspace(0, events.size, bands + 1).astype(int)
    return [float(events[a:b].mean()) if b > a else float("nan")
            for a, b in zip(edges[:-1], edges[1:], strict=True)]


# ----------------------------------------------------------- distribution


def bin_counts(values: pd.Series, edges: list[float]) -> np.ndarray:
    """How many values fall in each bin, edges left-open and right-closed.

    `np.searchsorted` rather than `pd.cut`: one fewer library making a
    decision about what a boundary means.
    """
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    inner = np.asarray(edges, dtype=float)
    index = np.searchsorted(inner, x, side="left")
    return np.bincount(index, minlength=inner.size + 1)


def population_stability(expected: np.ndarray, actual: np.ndarray) -> float:
    """PSI, written out.

        PSI = Σ (a_i − e_i) · ln(a_i / e_i)

    over shares rather than counts. An empty bin on either side makes the
    logarithm infinite, and this raises rather than substituting a small
    number: a PSI stabilised by an arbitrary epsilon is a number whose value
    depends on the epsilon, and quoting it as a drift measurement is how a
    threshold breach gets tuned away.
    """
    e = np.asarray(expected, dtype=float)
    a = np.asarray(actual, dtype=float)
    if e.sum() <= 0 or a.sum() <= 0:
        raise ValueError("PSI needs both distributions to be non-empty")
    e = e / e.sum()
    a = a / a.sum()

    total = 0.0
    for expected_share, actual_share in zip(e, a, strict=True):
        if expected_share <= 0 or actual_share <= 0:
            raise ValueError(
                "a bin is empty on one side; PSI is infinite there. The "
                "production kernel's handling of this is a policy decision "
                "and has to be compared against deliberately, not silently.")
        total += (actual_share - expected_share) * math.log(
            actual_share / expected_share)
    return total


def woe_and_iv(good: int, bad: int, good_total: int, bad_total: int,
               smoothing: float = 0.0) -> tuple[float, float]:
    """One bin's weight of evidence and its contribution to IV.

        WOE_i = ln( (good_i / good) / (bad_i / bad) )
        IV_i  = (good_i/good − bad_i/bad) · WOE_i

    `smoothing` adds a Laplace correction to both numerator and denominator.
    Zero is the textbook definition and is what a reader means by IV. The
    production kernel uses 0.5, a stated policy rather than an unexplained
    epsilon: a bin with no bads gives an infinite WOE, which then propagates
    through every score in that bin.

    Both are computed here so a reconciliation can pin the production figure
    EXACTLY against the smoothed formula and separately show how far the
    smoothing moves it. Widening a tolerance to absorb the difference would
    hide precisely the quantity worth knowing.
    """
    good_share = (good + smoothing) / (good_total + smoothing * 2)
    bad_share = (bad + smoothing) / (bad_total + smoothing * 2)
    if good_share <= 0 or bad_share <= 0:
        raise ValueError(
            "an empty bin has an infinite weight of evidence; with no "
            "smoothing there is no finite answer to return")
    woe = math.log(good_share / bad_share)
    return woe, (good_share - bad_share) * woe


def iv_over_bins(bins: pd.Series, events: pd.Series,
                 smoothing: float = 0.0) -> tuple[float, list[dict[str, Any]]]:
    """IV over bins that already exist, and the WOE table underneath it.

    Takes the bin ASSIGNMENT rather than raw values plus edges, because the
    approved bins are data: re-cutting them on the validation sample would
    measure a different, better, unapproved model and report it as this one's.
    What is independent here is the counting and the logarithms, which is
    where an IV goes wrong.
    """
    y = pd.to_numeric(events, errors="coerce")
    keep = y.notna() & bins.notna()
    y = (y[keep] > 0.5)
    b = bins[keep]

    bad_total = int(y.sum())
    good_total = int((~y).sum())
    if bad_total == 0 or good_total == 0:
        raise ValueError("IV needs both classes present")

    rows: list[dict[str, Any]] = []
    total = 0.0
    for level, part in y.groupby(b, observed=True):
        bad = int(part.sum())
        good = int(len(part) - bad)
        try:
            woe, contribution = woe_and_iv(good, bad, good_total, bad_total,
                                           smoothing)
        except ValueError:
            rows.append({"bin": level, "good": good, "bad": bad,
                         "woe": None, "contribution": None})
            continue
        total += contribution
        rows.append({"bin": level, "good": good, "bad": bad, "woe": woe,
                     "contribution": contribution})
    return total, rows


def information_value(values: pd.Series, events: pd.Series,
                      edges: list[float]) -> tuple[float, list[dict[str, Any]]]:
    """IV and the WOE table underneath it.

        WOE_i = ln( (good_i / good) / (bad_i / bad) )
        IV    = Σ (good_i/good − bad_i/bad) · WOE_i

    "Good" is a non-event and "bad" is an event, which is the convention this
    sign depends on — stated because the opposite convention flips every WOE
    and leaves IV unchanged, so an IV that agrees proves less than a WOE that
    agrees.
    """
    x = pd.to_numeric(values, errors="coerce")
    y = pd.to_numeric(events, errors="coerce")
    keep = x.notna() & y.notna()
    x, y = x[keep], (y[keep] > 0.5)

    inner = np.asarray(edges, dtype=float)
    index = np.searchsorted(inner, x.to_numpy(dtype=float), side="left")

    bad_total = int(y.sum())
    good_total = int((~y).sum())
    if bad_total == 0 or good_total == 0:
        raise ValueError("IV needs both classes present")

    rows: list[dict[str, Any]] = []
    total = 0.0
    for b in range(inner.size + 1):
        here = index == b
        bad = int(y.to_numpy()[here].sum())
        good = int(here.sum() - bad)
        if bad == 0 or good == 0:
            rows.append({"bin": b, "good": good, "bad": bad, "woe": None,
                         "contribution": None})
            continue
        woe = math.log((good / good_total) / (bad / bad_total))
        contribution = (good / good_total - bad / bad_total) * woe
        total += contribution
        rows.append({"bin": b, "good": good, "bad": bad, "woe": woe,
                     "contribution": contribution})
    return total, rows


# ------------------------------------------------------------ calibration


def observed_versus_predicted(frame: pd.DataFrame, *, pd_column: str,
                              outcome: str) -> dict[str, float]:
    """The whole-portfolio calibration ratio, and the two means behind it.

    Deliberately ungrouped. A banded comparison can be right in every band and
    wrong overall if the bands are chosen after the fact, and the portfolio
    ratio is the number a committee actually argues about.
    """
    p = pd.to_numeric(frame[pd_column], errors="coerce")
    y = pd.to_numeric(frame[outcome], errors="coerce")
    keep = p.notna() & y.notna()
    predicted = float(p[keep].mean())
    observed = float((y[keep] > 0.5).mean())
    if predicted <= 0:
        raise ValueError("a predicted rate of zero has no calibration ratio")
    return {"predicted": predicted, "observed": observed,
            "ratio": observed / predicted, "rows": int(keep.sum())}


def calibration_by_band(frame: pd.DataFrame, *, score: str, pd_column: str,
                        outcome: str, bands: int = 10
                        ) -> list[dict[str, float]]:
    """Predicted against observed, in equal-count score bands."""
    work = frame[[score, pd_column, outcome]].apply(
        pd.to_numeric, errors="coerce").dropna()
    work = work.sort_values(score, kind="mergesort").reset_index(drop=True)
    edges = np.linspace(0, len(work), bands + 1).astype(int)
    out: list[dict[str, float]] = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        if b <= a:
            continue
        chunk = work.iloc[a:b]
        out.append({
            "rows": int(len(chunk)),
            "predicted": float(chunk[pd_column].mean()),
            "observed": float((chunk[outcome] > 0.5).mean()),
        })
    return out


__all__ = [
    "Cohort", "analytics_root", "auc_pairwise", "auc_trapezoid",
    "bin_counts", "calibration_by_band", "cohort", "gini",
    "information_value", "iv_over_bins", "ks", "observed_versus_predicted",
    "partitions", "population_stability", "rank_order", "read",
    "woe_and_iv",
]
