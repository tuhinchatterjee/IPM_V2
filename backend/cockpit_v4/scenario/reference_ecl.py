"""The synthetic reference ECL calculator, written down rather than assumed.

**This is not a bank engine.** It is a documented calculator written for this
demonstration, and every figure it produces is `SYNTHETIC_DEMO`. Section 11.1
is explicit about why that distinction has to be kept: *"Do not manufacture the
training label as PD x LGD x EAD and then claim the resulting model learned the
bank's ECL engine."* This module is the reason the candidate release's ECL is
NOT that product — it is a probability-weighted, term-structured, discounted
measurement with a management overlay on top, which is a function an emulator
can actually be asked to learn rather than a three-way multiplication it would
recover to machine precision.

The two accepted books measure ECL as exactly `ead x pd x lgd`. That is what
made proportional Delta exact there, and it is also what makes them useless as
an ML target. The gap between the two facts is this file.

---

## The measurement

For one exposure at one reporting date, under one economic scenario `s`:

    ECL_s = SUM over horizon buckets h of
              survival[h] x pd_marginal[h] x lgd[h] x ead[h] x discount[h]

and across scenarios:

    ECL_modelled = SUM over s of weight[s] x ECL_s          (weights sum to 1)
    ECL_total    = ECL_modelled + overlay

where

* `pd_marginal[h]` is the probability of defaulting inside bucket `h`, given
  survival to its start. It comes from an annual hazard for that bucket,
  converted to the bucket's own length: `1 - (1 - hazard)^(months/12)`.
* `survival[h]` is the product of `(1 - pd_marginal[j])` over the earlier
  buckets, and `survival[0] = 1`.
* `discount[h]` is `(1 + eir) ^ (-midpoint_months / 12)` at the exposure's own
  effective interest rate, taken at the bucket's midpoint.
* Buckets beyond remaining maturity are dropped, and a bucket the maturity
  falls inside is included for the fraction of its length that survives.

**Twelve-month against lifetime.** Bucket 0 is exactly twelve months long in
both books, so the twelve-month figure is bucket 0's contribution and the
lifetime figure is every bucket's — no partial-bucket apportionment, and no
approximating lifetime by multiplying an annual number by a number of years,
which section 8 names as an error. Stage 1 recognises the twelve-month figure;
Stages 2 and 3 recognise the lifetime figure.

**Stage 3.** Default has happened: the first bucket's hazard is 1, so the whole
exposure is at risk immediately and the measurement reduces to
`lgd[0] x ead[0] x discount[0]`. It is still discounted, which is why a Stage 3
ECL here is not simply `ead x lgd`.

## What is deliberately NOT here

No calibration to any real portfolio, no regulatory interpretation, and no
claim that these shapes are the ones a bank would use. The hazard, LGD and
amortisation shapes are declared inputs, published beside the results in
`whatif_*_term_structure`, and a reader can recompute every published number
from them. That is the whole of what "independent reference calculator" means
in section 11.4: something the emulator can be checked AGAINST, which was not
used to fit it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.cockpit_v4.generate.totals import exact_total

#: The calculator's own version. Published on every row it produces, so a
#: figure can be traced to the arithmetic that made it and a later change to
#: these formulas is a new version rather than a silent restatement.
VERSION = "whatif-reference-ecl-1.0.0"

#: Bucket lengths in months. Bucket 0 is twelve months in both books, which is
#: what makes the twelve-month figure exact rather than apportioned.
CORPORATE_BUCKETS: tuple[int, ...] = (12, 12, 12, 24, 60)
RETAIL_BUCKETS: tuple[int, ...] = (12, 12, 24)

#: How the annual hazard moves across buckets, relative to the twelve-month
#: PD. Declining, because a facility that has survived its first year has
#: shown something; the shape is a declared assumption, not an estimate.
CORPORATE_HAZARD_SHAPE: tuple[float, ...] = (1.0, 0.92, 0.84, 0.76, 0.68)
RETAIL_HAZARD_SHAPE: tuple[float, ...] = (1.0, 0.88, 0.74)

#: How LGD moves across buckets. Rising slightly: collateral values age and
#: recovery takes longer the further out a default happens.
CORPORATE_LGD_SHAPE: tuple[float, ...] = (1.0, 1.02, 1.04, 1.07, 1.11)
RETAIL_LGD_SHAPE: tuple[float, ...] = (1.0, 1.03, 1.06)

#: How exposure amortises across buckets, as a fraction of the reporting-date
#: exposure still outstanding at each bucket's midpoint.
CORPORATE_EAD_SHAPE: tuple[float, ...] = (1.0, 0.94, 0.87, 0.78, 0.62)
RETAIL_EAD_SHAPE: tuple[float, ...] = (1.0, 0.90, 0.76)

#: The twelve-month horizon, in months. Named because it appears in three
#: places and a stray 12 in any of them would be a different measurement.
TWELVE_MONTHS = 12

#: Published figures are rounded here, once, at the end. Six places on a
#: SAR-million amount is a tenth of a riyal.
PLACES = 6


@dataclass(frozen=True)
class Bucket:
    """One horizon bucket of one exposure under one scenario."""

    index: int
    start_month: float
    end_month: float
    months: float
    hazard: float
    pd_marginal: float
    survival: float
    pd_cumulative: float
    lgd: float
    ead: float
    discount_factor: float
    expected_shortfall: float


@dataclass(frozen=True)
class Measurement:
    """What one exposure measures to, and the pieces it is made of."""

    ecl_12m: float
    ecl_lifetime: float
    ecl_recognised: float
    overlay: float
    ecl_total: float
    stage: int
    #: Per scenario, the buckets that produced it. Published as the term
    #: structure so the totals above can be recomputed by a reader.
    buckets: dict[str, tuple[Bucket, ...]]

    def rate(self, denominator: float) -> float:
        """Total ECL over its declared denominator.

        Section 11.1: the ML target is an ECL RATE on a declared denominator,
        and a rate whose denominator is not stated is not a rate. Zero
        denominator returns zero rather than raising: an exposure of nothing
        has no rate, and the row is excluded from training on that basis
        rather than carrying an infinity.
        """
        if denominator <= 0:
            return 0.0
        return round(self.ecl_total / denominator, 8)


def hazard_for(pd_12m: float, shape: float) -> float:
    """The annual hazard in a bucket, from the twelve-month PD and its shape.

    Clamped below one: a hazard of one means certain default within the year,
    which is Stage 3's case and is set directly rather than reached by scaling.
    """
    return min(max(pd_12m * shape, 0.0), 0.999999)


def discount_factor(eir: float, months: float) -> float:
    """`(1 + eir) ^ (-years)`, at the bucket midpoint.

    A zero or negative rate returns 1: this calculator does not model negative
    discounting, and silently producing a factor above one would make a
    distant loss larger than a near one.
    """
    if eir <= 0:
        return 1.0
    return float((1.0 + eir) ** (-months / 12.0))


def term_structure(*, pd_12m: float, lgd: float, ead: float, eir: float,
                   remaining_maturity_months: float,
                   buckets: tuple[int, ...],
                   hazard_shape: tuple[float, ...],
                   lgd_shape: tuple[float, ...],
                   ead_shape: tuple[float, ...],
                   defaulted: bool = False) -> tuple[Bucket, ...]:
    """The full profile for one exposure under one scenario.

    `defaulted` is Stage 3: the first bucket's hazard is 1 and there is
    nothing after it, because default has already happened and the question is
    only what is recovered.
    """
    if not (len(buckets) == len(hazard_shape) == len(lgd_shape)
            == len(ead_shape)):
        raise ValueError(
            "the bucket lengths and the three shapes must describe the same "
            "number of buckets; a shape shorter than the term structure "
            "would silently truncate the measurement.")

    out: list[Bucket] = []
    survival = 1.0
    start = 0.0
    for index, length in enumerate(buckets):
        end = start + float(length)
        if remaining_maturity_months <= start:
            break
        # A bucket the maturity falls inside counts for the part of itself
        # that survives, not for all of it and not for none of it.
        months = min(float(length), remaining_maturity_months - start)

        if defaulted:
            hazard = 1.0 if index == 0 else 0.0
            marginal = 1.0 if index == 0 else 0.0
        else:
            hazard = hazard_for(pd_12m, hazard_shape[index])
            marginal = 1.0 - (1.0 - hazard) ** (months / 12.0)

        bucket_lgd = min(max(lgd * lgd_shape[index], 0.0), 1.0)
        bucket_ead = max(ead * ead_shape[index], 0.0)
        midpoint = start + months / 2.0
        factor = discount_factor(eir, midpoint)
        shortfall = survival * marginal * bucket_lgd * bucket_ead * factor

        out.append(Bucket(
            index=index, start_month=start, end_month=start + months,
            months=months, hazard=hazard, pd_marginal=marginal,
            survival=survival,
            pd_cumulative=1.0 - survival * (1.0 - marginal),
            lgd=bucket_lgd, ead=bucket_ead, discount_factor=factor,
            expected_shortfall=shortfall))

        survival *= (1.0 - marginal)
        start = end
        if defaulted:
            break
    return tuple(out)


def horizon_ecl(buckets: tuple[Bucket, ...], *, months: float) -> float:
    """The ECL of the buckets that begin inside a horizon.

    `months = TWELVE_MONTHS` gives the twelve-month figure and
    `float("inf")` the lifetime one. Bucket 0 is exactly twelve months long in
    both books, so neither answer apportions a bucket.
    """
    return exact_total(b.expected_shortfall for b in buckets
                       if b.start_month < months)


def weighted(per_scenario: dict[str, tuple[Bucket, ...]],
             weights: dict[str, float], *, months: float) -> float:
    """The probability-weighted ECL across economic scenarios.

    Section 9.1 wants the scenario dimension explicit. The weights are
    required to sum to one: a set that does not is either missing a scenario
    or double-counting one, and scaling them silently would hide which.
    """
    total = exact_total(weights.get(name, 0.0) for name in per_scenario)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            f"scenario weights sum to {total}, not 1. A weighted ECL over "
            f"weights that do not sum to one is not an expectation.")
    return exact_total(weights[name] * horizon_ecl(buckets, months=months)
                       for name, buckets in per_scenario.items())


def measure(*, per_scenario: dict[str, tuple[Bucket, ...]],
            weights: dict[str, float], stage: int,
            overlay: float = 0.0) -> Measurement:
    """The recognised ECL for one exposure, and the pieces behind it.

    Stage 1 recognises the twelve-month figure; Stages 2 and 3 recognise the
    lifetime figure. That is the whole of the stage rule here, and section 8
    is why it is stated rather than approximated: twelve-month and lifetime
    ECL are different measurements, and multiplying an annual number by a
    number of years is not a conversion between them.
    """
    if stage not in (1, 2, 3):
        raise ValueError(f"stage {stage!r} is not 1, 2 or 3.")
    twelve = weighted(per_scenario, weights, months=float(TWELVE_MONTHS))
    lifetime = weighted(per_scenario, weights, months=math.inf)
    recognised = twelve if stage == 1 else lifetime
    return Measurement(
        ecl_12m=round(twelve, PLACES),
        ecl_lifetime=round(lifetime, PLACES),
        ecl_recognised=round(recognised, PLACES),
        overlay=round(overlay, PLACES),
        ecl_total=round(recognised + overlay, PLACES),
        stage=stage, buckets=per_scenario)


def profile(domain_shapes: str) -> dict[str, tuple]:
    """The declared shapes for a book, in one object.

    Named rather than passed around loose, because a Corporate hazard shape
    applied to a Retail exposure would produce a plausible number from the
    wrong assumption, and nothing downstream would say so.
    """
    if domain_shapes == "corporate":
        return {"buckets": CORPORATE_BUCKETS,
                "hazard_shape": CORPORATE_HAZARD_SHAPE,
                "lgd_shape": CORPORATE_LGD_SHAPE,
                "ead_shape": CORPORATE_EAD_SHAPE}
    if domain_shapes == "retail":
        return {"buckets": RETAIL_BUCKETS,
                "hazard_shape": RETAIL_HAZARD_SHAPE,
                "lgd_shape": RETAIL_LGD_SHAPE,
                "ead_shape": RETAIL_EAD_SHAPE}
    raise ValueError(f"{domain_shapes!r} has no declared term-structure "
                     f"profile. The books are 'corporate' and 'retail'.")


__all__ = [
    "Bucket", "CORPORATE_BUCKETS", "CORPORATE_EAD_SHAPE",
    "CORPORATE_HAZARD_SHAPE", "CORPORATE_LGD_SHAPE", "Measurement", "PLACES",
    "RETAIL_BUCKETS", "RETAIL_EAD_SHAPE", "RETAIL_HAZARD_SHAPE",
    "RETAIL_LGD_SHAPE", "TWELVE_MONTHS", "VERSION", "discount_factor",
    "hazard_for", "horizon_ecl", "measure", "profile", "term_structure",
    "weighted",
]
