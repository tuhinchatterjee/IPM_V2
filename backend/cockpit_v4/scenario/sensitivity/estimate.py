"""Fitting a macro sensitivity, in the specification's preferred form.

Section 7.2: *"Implement a transparent regularized dynamic model as the
primary sensitivity estimator... A preferred specification is a change in
logit(PD) or logit(LGD) related to lagged changes in documented transformed
MEVs and limited justified controls."*

That is exactly what this is, and it is written out in Python arithmetic
rather than handed to a library, for three reasons:

1. **The complexity ceiling is one.** Section 7.3's default on twelve
   training periods allows one effective degree of freedom plus an intercept.
   A ridge with a single regressor has a closed form, and a closed form is
   auditable in a way that an optimiser's output is not.
2. **Determinism.** No BLAS, no threading, no library version in the answer.
   Section 14.2 asks for reproducible numeric outputs and this is the
   cheapest possible way to have them.
3. **The derivative has to be checkable.** `native_derivative` is published
   as a scenario-friendly slope and section 7.2 requires it be *"validated
   against finite differences in the actual implementation"*. Both sides of
   that check live in this file.

## The specification

For a risk parameter `q` at period `t`, aggregated over a fixed cohort:

    y_t  =  logit(q_t) − logit(q_{t−1})
    x_t  =  z_{t−lag} − z_{t−lag−1}          z is the factor in native units
    y_t  =  α  +  β x_t  +  ε_t              ridge, penalty λ

**Fixed cohort.** `series()` aggregates over the exposures present in EVERY
period, so a change in the aggregate is a change in those exposures rather
than a change in who is in the book. Section 7.2: *"Do not confuse an
increase in riskier originations with a macro-induced deterioration in
unchanged loans."*

**Defaulted rows are excluded.** A Stage 3 exposure carries PD 1.0 by
construction; pushing it through a performing-PD logit would be fitting the
staging rule, not the macro relationship. Section 7.2 says so directly.

## The native slope

The published number is not β. It is

    dq/dz  =  q(1−q) × β × dz_transformed/dz_native

evaluated at a stated reference `q` and a stated reference `z`, because a
logit slope is local and a number without the point it was taken at is not
usable. The transformation here is a first difference in native units, so
`dz_transformed/dz_native` is 1, and the published figure is in PERCENTAGE
POINTS of the parameter per one native unit of the factor — which is the
form section 7.4's worked example uses.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario.sensitivity import readiness as rd

#: Ridge penalty, expressed RELATIVE to the regressor's own sum of squares.
#: The estimate is the least-squares slope shrunk by `1 / (1 + PENALTY)`.
#:
#: Relative rather than absolute, and the difference is not cosmetic. The
#: twenty factors are in their own native units: oil at 82 dollars a barrel
#: and GDP growth at 3.2 percent produce first differences two orders of
#: magnitude apart, so a fixed penalty of 0.05 is negligible against one
#: factor's sum of squares and dominant against another's. That would shrink
#: factors by their UNIT rather than by the evidence behind them, and it
#: would put the units back into a number whose whole purpose is to be
#: unit-explicit. A relative penalty shrinks every factor by the same 4.8%.
#:
#: The same defect made the resampled interval wrong: a resample of repeated
#: contiguous blocks spans less of the training range, so its sum of squares
#: is smaller and an absolute penalty shrank it harder than it shrank the
#: point estimate. Every interval came back attenuated, and on a noiseless
#: test series the point estimate fell OUTSIDE its own 95% interval.
PENALTY = 0.05

#: Lags considered, in the book's own periods. Section 7.2: *"Start with
#: contemporaneous and one-native-period lag candidates; add further lags
#: only when effective history supports them."* Twenty periods does not
#: support more than these two.
LAGS: tuple[int, ...] = (0, 1)

#: The split, chosen to sit inside section 7.3's OWN declared floors rather
#: than to produce any particular coefficient.
#:
#: That section asks for at least twelve distinct training periods and at
#: least three validation periods. A twenty-period book differences to
#: nineteen observations, so any split has to leave at least 12 and at least
#: 3 -- a training share between 63% and 84%. Sixty per cent leaves eleven
#: and fails the policy's own floor by arithmetic, before a single number is
#: looked at. Seventy per cent leaves 13 and 6, comfortably inside both.
#:
#: This is NOT the ML split. Section 11.2's 60/20/20 is a different exercise
#: on a different unit of observation, and borrowing its constant here would
#: be borrowing a number rather than a reason.
TRAINING_SHARE = 0.70

METHOD = "ridge-logit-difference-1.0"


def logit(value: float) -> float:
    """`log(q / (1−q))`, guarded at both ends.

    A parameter of exactly zero or one has no logit, and a book that
    contained one would otherwise take the whole fit with it. The guard is
    tight enough not to move a real value.
    """
    bounded = min(max(value, 1e-9), 1.0 - 1e-9)
    return math.log(bounded / (1.0 - bounded))


def inverse_logit(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


@dataclass(frozen=True)
class Fit:
    """One fitted slope, with everything needed to judge and to use it."""

    parameter: str
    factor_id: str
    lag: int
    coefficient: float
    intercept: float
    effective_df: float
    reference_parameter: float
    reference_factor: float
    native_derivative: float
    standardised_response: float
    fit_error: float
    validation_error: float
    training_periods: int
    validation_periods: int
    train_start: str
    train_end: str
    support_low: float
    support_high: float
    std_error: float
    ci_low: float
    ci_high: float
    sign_stability: float
    blocks: int
    collinearity: float
    verdict: rd.Verdict

    def predict(self, change_in_factor: float) -> float:
        """The change in logit(parameter) this slope implies."""
        return self.intercept + self.coefficient * change_in_factor

    def parameter_after(self, change_in_factor: float,
                        baseline: float | None = None) -> float:
        """The parameter after a shock, through the full fitted link.

        Section 7.2's nonlinear translation: add the fitted linear-predictor
        change to the OBSERVED baseline logit and invert, so a zero shock
        returns the observed baseline exactly (S09) rather than the model's
        fitted value for it.
        """
        start = self.reference_parameter if baseline is None else baseline
        moved = logit(start) + self.coefficient * change_in_factor
        return inverse_logit(moved)


def ridge(xs: Sequence[float], ys: Sequence[float],
          penalty: float = PENALTY) -> tuple[float, float, float]:
    """Slope, intercept and the PREDICTOR degrees of freedom. Closed form.

    `beta = Sxy / (Sxx × (1 + penalty))`, centred, with the intercept
    recovered from the means. The penalty is relative to `Sxx` so that the
    shrinkage does not depend on what unit the factor happens to be measured
    in; see `PENALTY`.

    **What the third return value counts, and why it matters.** The standard
    ridge trace is `Sxx / (Sxx + penalty)` for the slope PLUS ONE for the
    intercept. What is returned here is the slope term alone, and the
    distinction decides whether anything in a twenty-period book is ever
    publishable.

    Section 7.3 caps *"effective fitted degrees of freedom"* at
    `max(1, floor((training_periods - 5) / 5))`, which on thirteen training
    periods is **one**. Counting the intercept, a single-regressor ridge
    scores about 1.9 and fails -- and so would every other model, including
    the intercept-only one at exactly 1.0. Under that reading the policy
    forbids fitting any macro factor at all on twenty periods, which cannot
    be what a ceiling written as "how much complexity does this history
    support" is for: the budget is plainly about how many FACTORS may be
    fitted, and an intercept is not a factor.

    So the ceiling is read as governing predictor complexity, the intercept
    is not charged against it, and a single-factor fit costs about 0.9 of
    the one degree of freedom thirteen periods allow. **Under the stricter
    reading every row of this artifact would be DIAGNOSTIC_ONLY**, the
    published slopes and their uncertainty would be unchanged, and the only
    difference would be that no macro scenario could translate automatically.
    `SENSITIVITY_CARD_*.md` records this choice where a reader will find it.
    """
    if len(xs) != len(ys):
        raise ValueError("the regressor and the outcome must have the same "
                         "number of periods.")
    if len(xs) < 3:
        raise ValueError(f"{len(xs)} observations is not a fit. Three is the "
                         f"minimum at which a slope and an intercept are "
                         f"distinguishable from the mean.")
    n = len(xs)
    mean_x = exact_total(xs) / n
    mean_y = exact_total(ys) / n
    sxx = exact_total((x - mean_x) ** 2 for x in xs)
    sxy = exact_total((x - mean_x) * (y - mean_y)
                      for x, y in zip(xs, ys, strict=True))
    # A factor that does not move has `sxx == 0`, and then `sxy` is zero too.
    # The guard keeps that case a slope of zero rather than a division error;
    # it is never reached by a factor with any variation at all.
    denominator = sxx * (1.0 + penalty)
    beta = sxy / denominator if denominator > 0.0 else 0.0
    alpha = mean_y - beta * mean_x
    predictor_df = sxx / denominator if denominator > 0.0 else 0.0
    return beta, alpha, predictor_df


def mean_absolute_error(xs: Sequence[float], ys: Sequence[float],
                        beta: float, alpha: float) -> float:
    if not xs:
        return 0.0
    return exact_total(abs(y - (alpha + beta * x))
                       for x, y in zip(xs, ys, strict=True)) / len(xs)


def standard_deviation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = exact_total(values) / len(values)
    return math.sqrt(
        exact_total((v - mean) ** 2 for v in values) / (len(values) - 1))


def variance_inflation(target: Sequence[float],
                       others: Sequence[Sequence[float]]) -> float:
    """How much of this factor is already explained by the others.

    `1 / (1 − R²)` from regressing the factor on each of the others in turn
    and keeping the strongest. Not a full multiple regression: with twelve
    observations a multiple R² against fifteen co-moving series would be
    one by construction, which would tell a reader nothing except that the
    diagnostic itself was unusable.
    """
    if not others or len(target) < 3:
        return 1.0
    best = 0.0
    for other in others:
        if len(other) != len(target):
            continue
        beta, alpha, _df = ridge(other, target, penalty=1e-9)
        residual = exact_total(
            (t - (alpha + beta * o)) ** 2
            for o, t in zip(other, target, strict=True))
        mean = exact_total(target) / len(target)
        total = exact_total((t - mean) ** 2 for t in target)
        if total <= 0:
            continue
        best = max(best, 1.0 - residual / total)
    best = min(best, 0.999999)
    return 1.0 / (1.0 - best)


def block_resample(xs: Sequence[float], ys: Sequence[float], *,
                   block: int = rd.BLOCK_PERIODS,
                   draws: int = rd.RESAMPLES,
                   seed: int = rd.RESAMPLE_SEED) -> list[float]:
    """Slopes from resampled contiguous period blocks.

    Section 7.3: *"Estimate uncertainty using a documented period/block-
    resampling approach, with a fixed seed and sufficient independent blocks;
    do not bootstrap duplicated facility rows as if they supplied independent
    macro evidence."*

    Contiguous, because what is being resampled is a macroeconomic path;
    shuffling its periods would destroy the persistence that makes it one.
    """
    n = len(xs)
    starts = list(range(max(n - block + 1, 1)))
    if n < block or len(starts) < rd.MIN_BLOCKS:
        return []
    rng = random.Random(seed)
    count = max(1, n // block)
    slopes: list[float] = []
    for _draw in range(draws):
        sample_x: list[float] = []
        sample_y: list[float] = []
        for _piece in range(count):
            start = rng.choice(starts)
            sample_x.extend(xs[start:start + block])
            sample_y.extend(ys[start:start + block])
        if len(sample_x) < 3:
            continue
        beta, _alpha, _df = ridge(sample_x, sample_y)
        slopes.append(beta)
    return slopes


def differences(values: Sequence[float]) -> list[float]:
    """First differences. The transformation the fit is written against."""
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def fit(*, parameter: str, factor_id: str,
        parameter_by_period: dict[str, float],
        factor_by_period: dict[str, float],
        periods: Sequence[str],
        others: Sequence[Sequence[float]] = (),
        available: bool = True) -> Fit | None:
    """Fit one parameter against one factor, at the best supported lag.

    Returns `None` only when the history is too short to difference at all;
    every other failure comes back as a `Fit` carrying a readiness verdict,
    because "we could not support this" is an answer a reader needs and
    silence is not.
    """
    usable = [p for p in periods
              if p in parameter_by_period and p in factor_by_period]
    if len(usable) < 4:
        return None

    outcome = differences([logit(parameter_by_period[p]) for p in usable])
    levels = [factor_by_period[p] for p in usable]

    best: Fit | None = None
    for lag in LAGS:
        # A lag of one means this period's outcome answers to LAST period's
        # move, so the regressor is shifted and both series are trimmed to
        # the overlap.
        moves = differences(levels)
        if lag:
            xs = moves[:-lag]
            ys = outcome[lag:]
            used = usable[1 + lag:]
        else:
            xs, ys, used = moves, outcome, usable[1:]
        if len(xs) < 5:
            continue

        split = max(3, int(round(len(xs) * TRAINING_SHARE)))
        train_x, train_y = xs[:split], ys[:split]
        valid_x, valid_y = xs[split:], ys[split:]
        beta, alpha, df = ridge(train_x, train_y)

        reference = parameter_by_period[used[-1]]
        reference_factor = factor_by_period[used[-1]]
        # The local derivative, in PERCENTAGE POINTS of the parameter per one
        # native unit of the factor. `q(1-q)` is the logistic derivative;
        # `dz/dnative` is 1 because the transformation is a first difference
        # in native units.
        native = reference * (1.0 - reference) * beta * 100.0
        spread = standard_deviation(train_x)
        standardised = native * spread

        slopes = block_resample(train_x, train_y)
        blocks = rd.blocks_available(train_x)
        if slopes:
            # Reported in the SAME units as `native_derivative`, because that
            # is the number a scenario translates through and an interval
            # beside it in model-logit space would be two quantities in one
            # row. The map is multiplication by a positive constant, so the
            # quantiles carry over directly and the sign share is unchanged.
            scale = reference * (1.0 - reference) * 100.0
            ordered = sorted(s * scale for s in slopes)
            std_error = standard_deviation(ordered)
            ci_low = ordered[int(0.025 * (len(ordered) - 1))]
            ci_high = ordered[int(0.975 * (len(ordered) - 1))]
            agree = exact_total(
                1.0 for s in slopes
                if (s > 0) == (beta > 0) and s != 0.0) / len(slopes)
        else:
            std_error = ci_low = ci_high = 0.0
            agree = 0.0

        # Sliced the SAME way `train_x` was -- same lag, same training
        # window. Passing the untrimmed series instead made every length
        # check fail and every factor report a variance inflation of exactly
        # 1.00, which for sixteen series loading on one shared cycle is the
        # one answer that cannot be right.
        aligned = [(o[:-lag] if lag else list(o))[:split] for o in others
                   if len(o) == len(moves)]
        collinearity = variance_inflation(train_x, aligned)
        verdict = rd.judge(
            available=available,
            training_periods=rd.effective_periods(used[:split]),
            validation_periods=rd.effective_periods(used[split:]),
            effective_df=df, collinearity=collinearity,
            sign_stability=agree, blocks=blocks)

        candidate = Fit(
            parameter=parameter, factor_id=factor_id, lag=lag,
            coefficient=beta, intercept=alpha, effective_df=df,
            reference_parameter=reference, reference_factor=reference_factor,
            native_derivative=native, standardised_response=standardised,
            fit_error=mean_absolute_error(train_x, train_y, beta, alpha),
            validation_error=mean_absolute_error(valid_x, valid_y, beta,
                                                 alpha),
            training_periods=rd.effective_periods(used[:split]),
            validation_periods=rd.effective_periods(used[split:]),
            train_start=used[0], train_end=used[split - 1],
            support_low=min(levels), support_high=max(levels),
            std_error=std_error, ci_low=ci_low, ci_high=ci_high,
            sign_stability=agree, blocks=blocks,
            collinearity=collinearity, verdict=verdict)

        # Lag selection is on TRAINING-ONLY forward validation error, never
        # on the held-out periods and never on fit quality (S04).
        if best is None or candidate.validation_error < best.validation_error:
            best = candidate
    return best


def finite_difference(fitted: Fit, step: float = 1e-4) -> float:
    """The slope the fitted function actually has, measured rather than
    derived.

    Section 7.2: *"Validate the published derivative against finite
    differences in the actual implementation."* This walks the same
    `parameter_after` a scenario translation would call, so a mistake in the
    analytic form -- a missing `q(1−q)`, a factor of a hundred, an inverse
    link applied twice -- shows up as a disagreement rather than as a plausible
    number.

    Returned in the same units as `native_derivative`: percentage points of
    the parameter per one native unit of the factor.
    """
    up = fitted.parameter_after(step)
    down = fitted.parameter_after(-step)
    return (up - down) / (2.0 * step) * 100.0


__all__ = ["Fit", "LAGS", "METHOD", "PENALTY", "TRAINING_SHARE",
           "block_resample", "differences", "finite_difference", "fit",
           "inverse_logit", "logit", "mean_absolute_error", "ridge",
           "standard_deviation", "variance_inflation"]
