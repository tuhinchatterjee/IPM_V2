"""What a twenty-period book is allowed to claim, and what it is not.

Section 7.3 is the most easily ignored part of the whole specification,
because ignoring it produces better-looking output. Twenty quarters repeated
across three thousand facilities give sixty thousand rows, and a fit on sixty
thousand rows reports tight standard errors, a high R-squared and twenty
confident coefficients. Every one of those numbers would be wrong, because
there are twenty independent macroeconomic observations in the data and no
amount of facility detail adds a twenty-first.

So the counting here is deliberately harsh:

* **Effective sample is DISTINCT REPORTING PERIODS.** Never rows, never
  entities, never row-periods. `effective_periods()` takes a set.
* **Complexity is capped by that count.** The proposed default is
  `max(1, floor((training_periods - 5) / 5))`, which on twelve training
  periods is **one** — one factor at a time plus an intercept, and no joint
  twenty-factor model at all.
* **Uncertainty comes from period blocks**, not from resampling duplicated
  facility rows, which would manufacture evidence out of the same twenty
  quarters over and over.
* **A factor that fails a gate gets a status, not a smaller coefficient.**

Section 7.3 also says what these numbers are: *"conservative product defaults
to make insufficiency visible, not universal statistical or regulatory
adequacy standards. They do not make a twelve-period model bank-validated."*
`SUPPORTED_ESTIMATE` in this artifact means "this book supports publishing
this slope", and nothing more.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: A slope this book's history supports publishing for a scenario.
SUPPORTED_ESTIMATE = "SUPPORTED_ESTIMATE"

#: A descriptive marginal relationship. Shown with its uncertainty and its
#: non-causal label, and NOT added to other marginals as if the set were a
#: jointly estimated model (section 7.3).
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"

#: The reader supplied it. Method 3's territory.
USER_ASSUMPTION = "USER_ASSUMPTION"

#: Fitted on generated data. True of everything in the candidate release, and
#: carried beside the statistical verdict rather than instead of it.
SYNTHETIC_DEMO = "SYNTHETIC_DEMO"

#: Too few distinct periods to fit anything at this complexity.
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"

#: The book has no series for this factor at all.
UNAVAILABLE = "UNAVAILABLE"

#: Fitted against a release that is no longer the one in use.
STALE = "STALE"

STATUSES: tuple[str, ...] = (
    SUPPORTED_ESTIMATE, DIAGNOSTIC_ONLY, USER_ASSUMPTION, SYNTHETIC_DEMO,
    INSUFFICIENT_HISTORY, UNAVAILABLE, STALE)

#: Section 7.3's proposed candidate defaults, named so a reader can see them
#: rather than infer them from behaviour.
MIN_TRAINING_PERIODS = 12
MIN_VALIDATION_PERIODS = 3

#: Variance inflation above which a factor is too entangled with the others
#: to carry its own coefficient. Twenty co-moving MEVs make this live.
MAX_COLLINEARITY = 5.0

#: The share of resamples that must agree with the point estimate's sign.
MIN_SIGN_STABILITY = 0.80

#: Block resampling. Contiguous blocks, because the thing being resampled is
#: a macroeconomic path and shuffling its periods would destroy the
#: persistence that makes it one.
RESAMPLES = 200
BLOCK_PERIODS = 4
RESAMPLE_SEED = 20260927

#: Below this many independent blocks, uncertainty is reported as not
#: reliably estimable rather than as a decorative interval.
MIN_BLOCKS = 3


def effective_periods(periods: Iterable[str]) -> int:
    """Distinct reporting periods. The only sample size that counts here.

    S03: *"Period count/effective complexity controls are not inflated by
    repeated facility rows."* Taking a set is the whole implementation, and
    it is a function rather than an inline `len(set(...))` so that the rule
    has a name a test can call.
    """
    return len(set(periods))


def max_effective_df(training_periods: int) -> float:
    """The complexity ceiling for this much history.

    `max(1, floor((training_periods - 5) / 5))`. On twenty quarters split
    twelve for training this is 1: one factor and an intercept. That is not
    a limitation of the estimator, it is what twelve macroeconomic
    observations support, and section 7.3 asks for it to be visible.
    """
    return float(max(1, math.floor((training_periods - 5) / 5)))


@dataclass(frozen=True)
class Verdict:
    """What a fitted slope is allowed to be called, and why."""

    status: str
    limitation: str

    @property
    def publishable(self) -> bool:
        """May a scenario translate a shock through this slope automatically?

        Only a supported estimate. A diagnostic is shown and explained; it is
        not applied without the reader saying so, which is section 7.3's
        *"Factors not supportably estimable remain unavailable for automatic
        translation unless the user supplies an explicit assumption."*
        """
        return self.status == SUPPORTED_ESTIMATE


def judge(*, available: bool, training_periods: int,
          validation_periods: int, effective_df: float,
          collinearity: float, sign_stability: float,
          blocks: int, synthetic: bool = True) -> Verdict:
    """The readiness verdict for one parameter-and-factor pair.

    Ordered from the most fundamental reason to the most statistical, so the
    sentence a reader sees names the FIRST thing that is wrong rather than
    the last one checked.
    """
    if not available:
        return Verdict(UNAVAILABLE, (
            "This book carries no series for this factor. It is unavailable, "
            "which is not the same as a sensitivity of zero."))

    if training_periods < MIN_TRAINING_PERIODS:
        return Verdict(INSUFFICIENT_HISTORY, (
            f"{training_periods} distinct training periods, against a "
            f"{MIN_TRAINING_PERIODS}-period floor. Facility rows do not "
            f"count: twenty quarters repeated across thousands of exposures "
            f"are still twenty quarters."))

    ceiling = max_effective_df(training_periods)
    if effective_df > ceiling + 1e-9:
        return Verdict(DIAGNOSTIC_ONLY, (
            f"Effective complexity {effective_df:.2f} exceeds the "
            f"{ceiling:.0f} this much history supports. Shown as a "
            f"descriptive marginal relationship, not as a jointly estimated "
            f"effect, and not to be added to other marginals."))

    if collinearity > MAX_COLLINEARITY:
        return Verdict(DIAGNOSTIC_ONLY, (
            f"Variance inflation {collinearity:.1f} against the other "
            f"retained factors. Twenty co-moving macro series do not carry "
            f"twenty separable effects, and this one's own contribution "
            f"cannot be told apart from theirs."))

    if validation_periods < MIN_VALIDATION_PERIODS:
        return Verdict(DIAGNOSTIC_ONLY, (
            f"{validation_periods} distinct validation periods, against a "
            f"{MIN_VALIDATION_PERIODS}-period floor. Forward validation on "
            f"fewer than three periods does not establish that the "
            f"relationship holds out of sample."))

    if blocks < MIN_BLOCKS:
        return Verdict(DIAGNOSTIC_ONLY, (
            f"{blocks} independent period blocks. Uncertainty is not "
            f"reliably estimable from fewer than {MIN_BLOCKS}, and an "
            f"interval computed anyway would be decoration."))

    if sign_stability < MIN_SIGN_STABILITY:
        return Verdict(DIAGNOSTIC_ONLY, (
            f"The sign agrees with the point estimate in only "
            f"{sign_stability:.0%} of period resamples. A slope whose "
            f"direction is not stable is not a slope to translate a scenario "
            f"through."))

    if synthetic:
        return Verdict(SUPPORTED_ESTIMATE, (
            "Supported by this release's history. The release is "
            "SYNTHETIC_DEMO: this establishes that the estimator recovers a "
            "relationship in generated data, not that the relationship holds "
            "in any real economy, and it is not a bank-validated "
            "sensitivity."))
    return Verdict(SUPPORTED_ESTIMATE, (  # pragma: no cover - no real book
        "Supported by this book's history under the stated readiness "
        "policy. Estimated under this sensitivity model; historical "
        "association is not a causal effect."))


def blocks_available(periods: Sequence[str],
                     block: int = BLOCK_PERIODS) -> int:
    """How many independent contiguous blocks this history holds."""
    return max(0, len(periods) // max(block, 1))


def is_stale(fitted_against: str, in_use: str) -> bool:
    """S16: a sensitivity fitted against different bytes is a different fit.

    Compared on the release FINGERPRINT rather than the id, because two
    builds under one id is exactly the substitution the fingerprint exists to
    detect, and a stale artifact reused silently is a scenario translated
    through numbers that describe a different book.
    """
    return bool(fitted_against) and bool(in_use) and fitted_against != in_use


__all__ = ["BLOCK_PERIODS", "DIAGNOSTIC_ONLY", "INSUFFICIENT_HISTORY",
           "MAX_COLLINEARITY", "MIN_BLOCKS", "MIN_SIGN_STABILITY",
           "MIN_TRAINING_PERIODS", "MIN_VALIDATION_PERIODS", "RESAMPLES",
           "RESAMPLE_SEED", "STALE", "STATUSES", "SUPPORTED_ESTIMATE",
           "SYNTHETIC_DEMO", "UNAVAILABLE", "USER_ASSUMPTION", "Verdict",
           "blocks_available", "effective_periods", "is_stale", "judge",
           "max_effective_df"]
