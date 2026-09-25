"""The twenty numbers a sensitivity is actually fitted on.

`estimate.py` knows how to fit a slope. This module decides WHAT it is fitted
to, and that decision carries more of section 7.2 than the estimator does:

* **The cohort is fixed.** Only exposures present in every period, so a
  movement in the aggregate is a movement in those exposures rather than a
  change in who is in the book. Section 7.2: *"Do not confuse an increase in
  riskier originations with a macro-induced deterioration in unchanged
  loans."*
* **The weights are frozen at the first period.** A fixed cohort is not
  enough on its own: EAD-weighting with live weights lets the aggregate move
  because a high-PD facility drew down, which is a composition effect wearing
  a macro effect's clothes. Freezing the weights removes it.
* **Defaulted exposures are out.** A Stage 3 exposure carries PD 1.0 by
  construction, so a book with more of them has a higher average PD for a
  reason that is the staging rule rather than the economy. Section 7.2 asks
  for Stage 3 to be handled separately and this is that: the cohort is the
  set that is performing in EVERY period, and the aggregate is a performing-
  book aggregate. The count that this removes is published beside the fit.
* **The sample is twenty periods.** Sixty thousand facility-quarters are
  twenty macroeconomic observations. `readiness.effective_periods` is what
  counts, and nothing here hands the estimator a longer vector than the
  calendar has.

## The digest

An artifact stored inside the release it describes cannot carry that
release's own fingerprint: the fingerprint is taken over the published bytes,
and the artifact is some of those bytes. `input_digest()` is the honest
substitute -- a SHA-256 over the exact series the fit consumed, and over the
cohort that produced them. Rebuilding the same release recomputes the same
digest; a generator change that moves a single period's aggregate moves it.
S16's staleness check compares the stored digest with the digest recomputed
from the release in use, and `source_release_id` catches the cruder case of
an artifact from another release entirely.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.generate.totals import exact_total
from backend.cockpit_v4.scenario.generate import macro as mv
from backend.cockpit_v4.scenario.sensitivity import PARAMETERS
from backend.cockpit_v4.scenario.sensitivity import estimate as est

#: The scenario the fit reads. A sensitivity describes how the book responds
#: to conditions; fitting it across the three weighted scenarios would be
#: fitting the scenario design rather than the response.
FIT_SCENARIO = "baseline"

#: Storage of each parameter in the book's own columns. `lgd_pct` is a
#: percent and the logit needs a fraction, so it is divided once here and the
#: published derivative comes back out in percentage points either way.
_AS_FRACTION = {"pd_pit_12m": 1.0, "pd_lifetime": 1.0, "lgd_pct": 100.0}


@dataclass(frozen=True)
class Book:
    """One book's fitting inputs, already reduced to period-level series."""

    domain_id: str
    release_id: str
    periods: tuple[str, ...]
    parameters: dict[str, dict[str, float]]
    factors: dict[str, dict[str, float]]
    cohort_size: int
    excluded_defaulted: int
    excluded_partial: int
    weight_period: str

    @property
    def digest(self) -> str:
        return input_digest(self)


def fixed_cohort(rows: Iterable[Mapping[str, Any]], *, key: str,
                 period_column: str,
                 periods: Sequence[str]) -> tuple[frozenset[str], int, int]:
    """The exposures a macro fit may read, and what leaving them out cost.

    Returns `(cohort, defaulted_dropped, partial_dropped)`. Both counts are
    published: a cohort that quietly discarded a third of the book would
    produce a clean-looking fit on a population the reader never agreed to.
    """
    seen: dict[str, set[str]] = {}
    defaulted: set[str] = set()
    for row in rows:
        entity = str(row[key])
        seen.setdefault(entity, set()).add(str(row[period_column]))
        if int(row.get("default_flag") or 0) or int(row.get("stage") or 0) >= 3:
            defaulted.add(entity)
    wanted = set(periods)
    complete = {e for e, got in seen.items() if wanted <= got}
    partial = len(seen) - len(complete)
    cohort = frozenset(complete - defaulted)
    return cohort, len(complete & defaulted), partial


def parameter_series(rows: Iterable[Mapping[str, Any]], *, key: str,
                     period_column: str, cohort: frozenset[str],
                     weight_period: str) -> dict[str, dict[str, float]]:
    """Frozen-weight cohort averages of each risk parameter, per period.

        q_t = SUM_i w_i q_{i,t} / SUM_i w_i        w_i = EAD_i at period 0

    The weights are a snapshot, not a series, which is the whole point. Every
    sum goes through `exact_total`, so the answer does not depend on the order
    the parquet happened to be read in.
    """
    weights: dict[str, float] = {}
    collected: dict[str, dict[str, list[tuple[float, float]]]] = {
        name: {} for name in PARAMETERS}
    for row in rows:
        entity = str(row[key])
        if entity not in cohort:
            continue
        period = str(row[period_column])
        if period == weight_period:
            weights[entity] = float(row["ead_sar_mn"])
    for row in rows:
        entity = str(row[key])
        if entity not in cohort:
            continue
        weight = weights.get(entity, 0.0)
        if weight <= 0.0:
            continue
        period = str(row[period_column])
        for name in PARAMETERS:
            value = float(row[name]) / _AS_FRACTION[name]
            collected[name].setdefault(period, []).append((weight, value))

    out: dict[str, dict[str, float]] = {}
    for name, by_period in collected.items():
        series: dict[str, float] = {}
        for period, pairs in by_period.items():
            total = exact_total(w for w, _v in pairs)
            if total <= 0:
                continue
            series[period] = exact_total(w * v for w, v in pairs) / total
        out[name] = series
    return out


def factor_series(domain_id: str,
                  periods: Sequence[str]) -> dict[str, dict[str, float]]:
    """Every factor this book carries, as `{factor_id: {period: value}}`.

    Read from the generator rather than from the published panel, because the
    two are the same numbers by construction and a test asserts it; an absent
    factor raises there and is simply not a key here.
    """
    return {factor_id: mv.series(domain_id, factor_id, tuple(periods),
                                 FIT_SCENARIO)
            for factor_id in sorted(mv.PRESENT[dom.parse(domain_id)])}


def unavailable(domain_id: str) -> list[tuple[str, str]]:
    """`(factor_id, reason)` for the factors this book has no series for."""
    present = mv.PRESENT[dom.parse(domain_id)]
    return [(f.factor_id, mv.ABSENT_REASON.get(
        f.factor_id,
        "This release does not generate a series for this factor. It is "
        "unavailable, which is not a sensitivity of zero."))
        for f in mv.FACTORS if f.factor_id not in present]


def conventions(domain_id: str) -> dict[str, str]:
    """Each present factor's shock convention, for the published unit."""
    return {f.factor_id: f.shock_convention for f in mv.FACTORS
            if f.factor_id in mv.PRESENT[dom.parse(domain_id)]}


def read_book(frames: Mapping[str, Any], *, domain_id: str, release_id: str,
              periods: Sequence[str], exposure_relation: str,
              key: str, period_column: str) -> Book:
    """Reduce one built release to its fitting inputs."""
    domain_id = dom.parse(domain_id)
    frame = frames[exposure_relation]
    rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
    cohort, defaulted, partial = fixed_cohort(
        rows, key=key, period_column=period_column, periods=periods)
    if not cohort:
        raise ValueError(
            f"no {key} is present in all {len(periods)} periods and "
            f"performing throughout. A macro sensitivity needs a cohort that "
            f"does not change between the periods being compared.")
    parameters = parameter_series(
        rows, key=key, period_column=period_column, cohort=cohort,
        weight_period=periods[0])
    return Book(
        domain_id=domain_id, release_id=release_id,
        periods=tuple(periods), parameters=parameters,
        factors=factor_series(domain_id, periods),
        cohort_size=len(cohort), excluded_defaulted=defaulted,
        excluded_partial=partial, weight_period=periods[0])


def input_digest(book: Book) -> str:
    """SHA-256 over the numbers the fit consumed. See the module docstring."""
    digest = hashlib.sha256()
    digest.update(book.release_id.encode())
    digest.update(f"|cohort={book.cohort_size}|".encode())
    for name in sorted(book.parameters):
        digest.update(f"|{name}|".encode())
        for period in book.periods:
            value = book.parameters[name].get(period)
            digest.update(f"{period}={value!r};".encode())
    for factor_id in sorted(book.factors):
        digest.update(f"|{factor_id}|".encode())
        for period in book.periods:
            value = book.factors[factor_id].get(period)
            digest.update(f"{period}={value!r};".encode())
    return digest.hexdigest()


def fit_book(book: Book) -> list[est.Fit]:
    """Every parameter against every factor this book carries.

    The other factors are passed to each fit so that the collinearity
    diagnostic is computed against the set actually retained -- sixteen series
    loading on one shared cycle is precisely the condition section 7.3 says a
    reader must be told about, and a variance inflation computed against
    nothing would report 1.00 and hide it.
    """
    ordered = sorted(book.factors)
    moves = {factor_id: est.differences(
        [book.factors[factor_id][p] for p in book.periods])
        for factor_id in ordered}
    fits: list[est.Fit] = []
    for parameter in PARAMETERS:
        series = book.parameters.get(parameter) or {}
        if not series:
            continue
        for factor_id in ordered:
            others = [moves[other] for other in ordered if other != factor_id]
            fitted = est.fit(
                parameter=parameter, factor_id=factor_id,
                parameter_by_period=series,
                factor_by_period=book.factors[factor_id],
                periods=book.periods, others=others, available=True)
            if fitted is not None:
                fits.append(fitted)
    return fits


__all__ = ["Book", "FIT_SCENARIO", "conventions", "factor_series",
           "fit_book", "fixed_cohort", "input_digest", "parameter_series",
           "read_book", "unavailable"]
