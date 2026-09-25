"""Two views of one change, and the cost of pretending they are one.

Section 13.2 asks for the headline change to be explained TWICE, and is
explicit that the two explanations are not to be combined:

* **The economic-driver view.** "Unemployment rose 1.5 points." The reader's
  own instruction, grouped as they gave it.
* **The risk-parameter mechanism.** "PD contributed 1,680 and LGD 880."
  What moved inside the calculation.

A macro instruction and the PD move it induced are the SAME change seen from
two sides. Adding them gives a total twice the size of the one that happened,
and the sentence in the specification is *"never add the two views
together"*. `Views.total_once` is what a caller gets instead: the headline,
attributed under whichever view was asked for, once.

## Three attribution methods, and when each is honest

| Groups | Method | Cost | Property |
|---|---|---|---|
| any | `SEQUENTIAL` | one pass per group | order-dependent, exact, telescopes |
| ≤ 8 | `SHAPLEY` | 2^n passes | order-independent, exact, splits interactions evenly |
| > 8 | `SAMPLED` | budgeted permutations | order-independent, approximate, with a stated error |

**Sequential is not wrong, it is a different question.** O04's own numbers:
PD-then-LGD gives 1,600 and 960 where Shapley gives 1,680 and 880. Both are
valid views of the same change and neither may be relabelled as the other,
so the order is published with a sequential bridge and the method is
published with every bridge.

**Above eight groups the exact answer is unaffordable** -- 2^9 is 512
population passes -- so contributions are estimated from randomly ordered
permutations with a fixed seed and a declared budget. That is an
approximation and it says so: `Bridge.convergence` carries the standard
error of each contribution across permutations, and `Bridge.residual` carries
what the bars do not explain.

**The residual is shown, never spread.** A bridge whose bars do not sum to
the headline has a residual, and distributing it across the drivers pro rata
makes every bar wrong in order to make the total look right. Section 13.2
asks for it to be displayed as its own item.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from backend.cockpit_v4.scenario import ledger as lg
from backend.cockpit_v4.scenario.errors import (
    RECONCILIATION_FAILED,
    raise_for,
)

#: The two views section 13.2 names. Labelled separately and never summed.
ECONOMIC = "economic_driver"
MECHANISM = "risk_parameter"
VIEWS = (ECONOMIC, MECHANISM)

VIEW_LABELS: dict[str, str] = {
    ECONOMIC: "What the reader changed",
    MECHANISM: "What moved inside the calculation",
}

#: The three attribution methods, named so a chart can say which it used.
SEQUENTIAL = lg.SEQUENTIAL
SHAPLEY = lg.SHAPLEY
SAMPLED = "sampled_shapley"
METHODS = (SEQUENTIAL, SHAPLEY, SAMPLED)

#: Above this many groups the exact Shapley is not computed. 2^8 is 256
#: population passes, which is affordable on a frozen cohort; 2^9 is 512,
#: which is not.
EXACT_LIMIT = 8

#: The sampling budget, declared rather than discovered. Permutations are
#: PAIRED -- each draw is evaluated forwards and backwards -- which cancels
#: most of the order effect and roughly halves the variance for the same
#: number of coalition evaluations.
PERMUTATIONS = 200
SAMPLE_SEED = 20261001

#: Above this relative standard error a sampled contribution is reported as
#: not having converged, rather than as a number with a decimal point.
CONVERGENCE_LIMIT = Decimal("0.10")


@dataclass(frozen=True)
class Bridge:
    """One view's attribution of one headline change."""

    view: str
    method: str
    baseline: Decimal
    headline: Decimal
    contributions: tuple[lg.Contribution, ...]
    #: Standard error per contribution, for `SAMPLED` only.
    convergence: dict[str, Decimal] = field(default_factory=dict)
    order: tuple[str, ...] = ()
    evaluations: int = 0
    notes: tuple[str, ...] = ()

    @property
    def explained(self) -> Decimal:
        return sum((c.change for c in self.contributions), Decimal(0))

    @property
    def residual(self) -> Decimal:
        """What the bars do not explain. Shown, never spread."""
        return self.headline - self.explained

    def converged(self) -> dict[str, bool]:
        """Per contribution: is its estimate tight enough to publish?"""
        if self.method != SAMPLED:
            return {c.label: True for c in self.contributions}
        out: dict[str, bool] = {}
        for contribution in self.contributions:
            error = self.convergence.get(contribution.label, Decimal(0))
            size = abs(contribution.change)
            out[contribution.label] = bool(
                size and error / size <= CONVERGENCE_LIMIT)
        return out

    def rows(self) -> list[dict[str, str]]:
        """The bridge as artifact rows, residual included as its own item."""
        converged = self.converged()
        out = [{
            "view": self.view, "method": self.method,
            "intervention": c.label, "fields": ", ".join(c.fields),
            "sequence": str(c.sequence),
            "change_sar_mn": str(c.change),
            "standard_error_sar_mn": str(
                self.convergence.get(c.label, Decimal(0))),
            "converged": "yes" if converged[c.label] else "NOT CONVERGED",
        } for c in self.contributions]
        if self.residual != 0:
            out.append({
                "view": self.view, "method": self.method,
                "intervention": "Unexplained residual",
                "fields": "", "sequence": str(len(out) + 1),
                "change_sar_mn": str(self.residual),
                "standard_error_sar_mn": "0",
                "converged": "n/a",
            })
        return out

    def describe(self) -> str:
        pieces = ", ".join(f"{c.label} {c.change:+,.2f}"
                           for c in self.contributions)
        head = (f"{VIEW_LABELS[self.view]}, attributed by {self.method}: "
                f"{pieces}.")
        if self.method == SEQUENTIAL and self.order:
            head += (f" Applied in this order: {' then '.join(self.order)}. "
                     f"A different order gives different bars for the same "
                     f"total, which is why the order is published with it.")
        if self.method == SAMPLED:
            head += (f" Estimated from {self.evaluations:,} paired "
                     f"permutations, seed {SAMPLE_SEED}. These are "
                     f"approximations with the standard error beside each.")
        if self.residual:
            head += (f" {self.residual:+,.2f} is unexplained and is shown as "
                     f"its own item rather than spread across the drivers.")
        return head


@dataclass(frozen=True)
class Views:
    """Both explanations of one change, kept apart."""

    economic: Bridge | None
    mechanism: Bridge | None
    headline: Decimal

    def total_once(self, view: str = ECONOMIC) -> Decimal:
        """The headline, attributed under ONE view. Never the sum of both."""
        if view not in VIEWS:
            raise ValueError(f"{view!r} is not a view. They are {VIEWS}.")
        return self.headline

    def rows(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for bridge in (self.economic, self.mechanism):
            if bridge is not None:
                out.extend(bridge.rows())
        return out

    def warning(self) -> str:
        return (
            "These are two views of ONE change, not two changes. A macro "
            "instruction and the risk-parameter move it induced are the same "
            "movement seen from two sides; adding the views together gives a "
            "total twice the size of what happened.")


def choose(groups: Sequence[str]) -> str:
    """Which method this many groups can afford, stated before it runs."""
    if len(groups) <= 1:
        return SEQUENTIAL
    return SHAPLEY if len(groups) <= EXACT_LIMIT else SAMPLED


def sequential(order: Sequence[str],
               cumulative: Sequence[tuple[str, tuple[str, ...], Decimal]], *,
               view: str, baseline: Decimal, headline: Decimal) -> Bridge:
    """The order-dependent bridge, with its order published."""
    contributions = lg.attribute(list(cumulative), baseline=baseline)
    return Bridge(view=view, method=SEQUENTIAL, baseline=baseline,
                  headline=headline, contributions=contributions,
                  order=tuple(order), evaluations=len(cumulative))


def exact(values: dict[frozenset[str], Decimal], *, view: str,
          baseline: Decimal, headline: Decimal) -> Bridge:
    """The order-independent bridge, for eight groups or fewer."""
    names = sorted({name for coalition in values for name in coalition})
    if len(names) > EXACT_LIMIT:
        raise_for(RECONCILIATION_FAILED,
                  f"an exact Shapley over {len(names)} groups needs "
                  f"{1 << len(names):,} population passes, past the "
                  f"{EXACT_LIMIT}-group limit this engine computes exactly. "
                  f"Use the sampled method, which says that it is an "
                  f"approximation.",
                  field_path="attribution.method", groups=len(names))
    contributions = lg.shapley(values, baseline=baseline)
    return Bridge(view=view, method=SHAPLEY, baseline=baseline,
                  headline=headline, contributions=contributions,
                  evaluations=1 << len(names))


def sampled(names: Sequence[str],
            value: Callable[[frozenset[str]], Decimal], *, view: str,
            baseline: Decimal, headline: Decimal,
            permutations: int = PERMUTATIONS,
            seed: int = SAMPLE_SEED) -> Bridge:
    """Shapley by paired random permutations, with its error reported.

    Each draw is evaluated in its own order and in the exact reverse, which
    cancels most of the order effect for the same number of coalition
    evaluations. The mean over draws is the estimate and the standard error
    over draws is published beside it; a contribution whose relative error
    exceeds `CONVERGENCE_LIMIT` is marked NOT CONVERGED rather than printed
    with a decimal point that suggests precision it does not have.

    Deterministic: one seed, one sequence of permutations, one answer.
    """
    names = list(names)
    if not names:
        return Bridge(view=view, method=SAMPLED, baseline=baseline,
                      headline=headline, contributions=())
    rng = random.Random(seed)
    draws: dict[str, list[Decimal]] = {name: [] for name in names}
    evaluations = 0

    for _draw in range(permutations):
        order = names[:]
        rng.shuffle(order)
        for direction in (order, list(reversed(order))):
            running = frozenset()
            previous = baseline
            for name in direction:
                running = running | {name}
                current = value(running)
                evaluations += 1
                draws[name].append(current - previous)
                previous = current

    contributions: list[lg.Contribution] = []
    errors: dict[str, Decimal] = {}
    for sequence, name in enumerate(sorted(names), start=1):
        sample = draws[name]
        mean = sum(sample, Decimal(0)) / len(sample)
        if len(sample) > 1:
            variance = sum(((v - mean) ** 2 for v in sample),
                           Decimal(0)) / (len(sample) - 1)
            errors[name] = (variance / len(sample)) ** Decimal("0.5")
        else:  # pragma: no cover - permutations is never one
            errors[name] = Decimal(0)
        contributions.append(lg.Contribution(
            label=name, fields=(name,), change=mean, sequence=sequence))

    return Bridge(
        view=view, method=SAMPLED, baseline=baseline, headline=headline,
        contributions=tuple(contributions), convergence=errors,
        evaluations=evaluations,
        notes=(f"{permutations:,} paired permutations, seed {seed}. "
               f"Approximate by construction; the standard error is "
               f"published with each contribution and the unexplained "
               f"residual is its own row.",))


def never_add(economic: Bridge, mechanism: Bridge) -> None:
    """The ban, as a function that only ever raises.

    Summing the two views double-counts every change: the macro instruction
    and the risk-parameter move it induced are one movement. Named so the
    ban has something a test can call and a caller reaching for it finds
    this instead of writing it.
    """
    raise_for(RECONCILIATION_FAILED,
              f"the economic-driver view explains {economic.explained} and "
              f"the risk-parameter view explains {mechanism.explained}, and "
              f"they are the SAME {economic.headline}. Adding them reports a "
              f"change twice the size of the one that happened. Show one "
              f"view, or show both side by side under their own labels.",
              field_path="attribution.views")


def check(bridge: Bridge, *, tolerance: Decimal = lg.CURRENCY) -> None:
    """The bars plus the residual land on the headline. Exactly."""
    total = bridge.explained + bridge.residual
    if abs(total - bridge.headline) > tolerance:
        raise_for(RECONCILIATION_FAILED,
                  f"this bridge's bars and residual sum to {total} and the "
                  f"headline change is {bridge.headline}. A reader adding "
                  f"the bars must land on the total.",
                  field_path="attribution.contributions")


__all__ = ["Bridge", "CONVERGENCE_LIMIT", "ECONOMIC", "EXACT_LIMIT",
           "MECHANISM", "METHODS", "PERMUTATIONS", "SAMPLED", "SAMPLE_SEED",
           "SEQUENTIAL", "SHAPLEY", "VIEWS", "VIEW_LABELS", "Views", "check",
           "choose", "exact", "never_add", "sampled", "sequential"]
